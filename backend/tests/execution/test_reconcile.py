"""对账：差异只记录不改数、重复对账不叠加、未处理差异阻断实盘。"""

from decimal import Decimal

from sqlalchemy import select

from app.execution import gate, models, reconcile
from app.ports.private import ExchangePosition
from tests.execution.conftest import seed_execution_strategy

ZERO = Decimal("0")


class StaticSource:
    """只提供对账所需的两个读接口；不构造任何网络客户端。"""

    def __init__(self, *, positions=(), orders=()) -> None:
        self._positions = list(positions)
        self._orders = list(orders)

    async def fetch_positions(self):
        return self._positions

    async def list_open_orders(self, *, inst_id: str | None = None):
        return self._orders


def _exchange_position(quantity: str) -> ExchangePosition:
    return ExchangePosition(
        inst_id="BTC-USDT-SWAP",
        position_side="long",
        quantity=Decimal(quantity),
        average_price=Decimal("100"),
        unrealized_pnl=ZERO,
    )


async def _seed_local_position(session, seeded, quantity: str = "1") -> None:
    session.add(
        models.Position(
            strategy_id=seeded.strategy_id,
            instrument_id=seeded.instrument_ids["BTC-USDT-SWAP"],
            inst_id="BTC-USDT-SWAP",
            position_side="long",
            quantity=Decimal(quantity),
            average_price=Decimal("100"),
            realized_pnl=ZERO,
        )
    )
    await session.commit()


async def test_position_mismatch_is_recorded_without_touching_local(session) -> None:
    seeded = await seed_execution_strategy(session)
    await _seed_local_position(session, seeded)

    result = await reconcile.run(session, source=StaticSource(positions=[_exchange_position("2")]))
    assert result["diffs"] == 1
    assert result["open_diffs"] == 1

    diff = (await session.execute(select(models.ReconcileDiff))).scalar_one()
    assert diff.kind == "position_mismatch"
    assert (diff.local_value, diff.exchange_value) == (Decimal("1"), Decimal("2"))

    position = (await session.execute(select(models.Position))).scalar_one()
    assert position.quantity == Decimal("1")


async def test_second_reconcile_does_not_duplicate_open_diff(session) -> None:
    seeded = await seed_execution_strategy(session)
    await _seed_local_position(session, seeded)
    source = StaticSource(positions=[_exchange_position("2")])

    await reconcile.run(session, source=source)
    await reconcile.run(session, source=source)

    diffs = list((await session.execute(select(models.ReconcileDiff))).scalars())
    assert len(diffs) == 1


async def test_open_diff_blocks_real_submission(session) -> None:
    seeded = await seed_execution_strategy(session)
    await _seed_local_position(session, seeded)
    await reconcile.run(session, source=StaticSource(positions=[_exchange_position("2")]))

    open_diffs = await reconcile.open_diff_count(session)
    assert open_diffs == 1
    decision = gate.check_submit(
        requested_mode=gate.MODE_REAL,
        real_trading_enabled=True,
        credentials_ready=True,
        strategy_id=seeded.strategy_id,
        authorized_strategy_ids=frozenset({seeded.strategy_id}),
        open_diffs=open_diffs,
    )
    assert decision.allowed is False
    assert decision.code == gate.CODE_RECONCILE_PENDING


async def test_missing_exchange_order_is_recorded(session) -> None:
    seeded = await seed_execution_strategy(session)
    session.add(
        models.Order(
            client_order_id="stuck-1",
            mode="paper",
            strategy_id=seeded.strategy_id,
            instrument_id=seeded.instrument_ids["BTC-USDT-SWAP"],
            inst_id="BTC-USDT-SWAP",
            side="buy",
            position_side="long",
            order_type="market",
            quantity=Decimal("1"),
            reduce_only=False,
            intent="entry",
            state="submitted",
            filled_quantity=ZERO,
            fee=ZERO,
        )
    )
    await session.commit()

    await reconcile.run(session, source=StaticSource())
    diff = (await session.execute(select(models.ReconcileDiff))).scalar_one()
    assert diff.kind == "order_missing_exchange"
    assert diff.reference == "stuck-1"


async def test_resolve_diff_closes_it(session) -> None:
    seeded = await seed_execution_strategy(session)
    await _seed_local_position(session, seeded)
    await reconcile.run(session, source=StaticSource(positions=[_exchange_position("2")]))
    diff = (await session.execute(select(models.ReconcileDiff))).scalar_one()

    resolved = await reconcile.resolve_diff(
        session, diff.id, resolved_by="p3-smoke", note="人工核对"
    )
    assert resolved["status"] == "resolved"
    assert resolved["resolved_by"] == "p3-smoke"
    assert await reconcile.open_diff_count(session) == 0

    # 差异再次出现时是一条新的 open 记录，历史结案记录保留。
    await reconcile.run(session, source=StaticSource(positions=[_exchange_position("2")]))
    assert await reconcile.open_diff_count(session) == 1
    assert len(list((await session.execute(select(models.ReconcileDiff))).scalars())) == 2

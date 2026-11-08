"""故障恢复：paper 重启接管、交易所查无此单时安全撤销、重复恢复幂等。"""

from decimal import Decimal

from sqlalchemy import select

from app.execution import models, paper, recovery, service
from tests.execution.conftest import seed_execution_strategy

ZERO = Decimal("0")


class MissingSource:
    """交易所侧什么也没有：所有查询返回空。"""

    async def fetch_order(self, **kwargs):
        return None

    async def fetch_fills(self, **kwargs):
        return []

    async def fetch_positions(self):
        return []

    async def list_open_orders(self, *, inst_id: str | None = None):
        return []


async def _paper_entry(session, seeded, client_order_id: str):
    body, _ = await service.submit_order(
        session,
        strategy_id=seeded.strategy_id,
        inst_id="BTC-USDT-SWAP",
        side="buy",
        position_side="long",
        quantity=Decimal("1"),
        client_order_id=client_order_id,
        mode="paper",
    )
    return body


async def _insert_order(
    session,
    seeded,
    *,
    client_order_id: str,
    state: str,
    mode: str = "paper",
    price: Decimal | None = None,
) -> None:
    session.add(
        models.Order(
            client_order_id=client_order_id,
            mode=mode,
            strategy_id=seeded.strategy_id,
            instrument_id=seeded.instrument_ids["BTC-USDT-SWAP"],
            inst_id="BTC-USDT-SWAP",
            side="buy",
            position_side="long",
            order_type="market",
            quantity=Decimal("1"),
            price=price,
            reduce_only=False,
            intent="entry",
            state=state,
            filled_quantity=ZERO,
            fee=ZERO,
        )
    )
    await session.commit()


async def test_paper_restart_rehydrates_and_finishes_order(session) -> None:
    seeded = await seed_execution_strategy(session)
    body = await _paper_entry(session, seeded, "restart-1")
    assert body["state"] == "partial"

    # 模拟进程重启：进程内撮合状态清零，只剩数据库里的订单与成交。
    paper.reset_paper_source()

    result = await recovery.run(session)
    assert result["rehydrated_orders"] == 1
    assert result["open_orders"] == 1
    assert result["reattached"] == 1
    assert result["rejected_unsent"] == 0
    assert result["canceled_missing"] == 0
    assert result["reconcile"]["open_diffs"] == 0

    order = (await session.execute(select(models.Order))).scalar_one()
    assert order.state == "filled"
    fills = list((await session.execute(select(models.Fill))).scalars())
    assert len(fills) == 2
    assert sum((item.quantity for item in fills), ZERO) == Decimal("1")

    position = (await session.execute(select(models.Position))).scalar_one()
    assert position.quantity == Decimal("1")


async def test_missing_on_exchange_is_cancelled_not_resent(session) -> None:
    seeded = await seed_execution_strategy(session)
    await _insert_order(session, seeded, client_order_id="never-sent", state="pending")
    await _insert_order(session, seeded, client_order_id="lost-order", state="submitted")

    result = await recovery.run(session, source=MissingSource())
    assert result["rejected_unsent"] == 1
    assert result["canceled_missing"] == 1

    rows = {
        row.client_order_id: row for row in (await session.execute(select(models.Order))).scalars()
    }
    assert rows["never-sent"].state == "rejected"
    assert rows["never-sent"].reject_reason == "recovered_unsent"
    assert rows["lost-order"].state == "canceled"
    assert rows["lost-order"].reject_reason == "recovered_missing_on_exchange"

    assert list((await session.execute(select(models.Fill))).scalars()) == []
    assert list((await session.execute(select(models.Position))).scalars()) == []


async def test_recovery_is_idempotent(session) -> None:
    seeded = await seed_execution_strategy(session)
    await _insert_order(session, seeded, client_order_id="lost-order", state="submitted")

    first = await recovery.run(session, source=MissingSource())
    second = await recovery.run(session, source=MissingSource())

    assert first["canceled_missing"] == 1
    assert second["open_orders"] == 0
    assert second["canceled_missing"] == 0
    order = (await session.execute(select(models.Order))).scalar_one()
    assert order.state == "canceled"


async def test_rehydrate_skips_real_mode_orders(session) -> None:
    seeded = await seed_execution_strategy(session)
    await _insert_order(
        session, seeded, client_order_id="paper-1", state="submitted", price=Decimal("100")
    )
    await _insert_order(
        session,
        seeded,
        client_order_id="real-1",
        state="submitted",
        mode="real",
        price=Decimal("100"),
    )

    rehydrated = await recovery._rehydrate_paper(session)
    assert rehydrated == 1

    source = paper.get_paper_source()
    assert (
        await source.fetch_order(inst_id="BTC-USDT-SWAP", client_order_id="paper-1")
    ) is not None
    assert (await source.fetch_order(inst_id="BTC-USDT-SWAP", client_order_id="real-1")) is None


async def test_zero_price_zombie_order_is_canceled_without_crash(session) -> None:
    seeded = await seed_execution_strategy(session)
    await _insert_order(session, seeded, client_order_id="zombie", state="submitted")
    paper.reset_paper_source()

    result = await recovery.run(session)
    assert result["rehydrated_orders"] == 0
    assert result["canceled_missing"] == 1

    order = (await session.execute(select(models.Order))).scalar_one()
    assert order.state == "canceled"
    assert order.reject_reason == "recovered_missing_on_exchange"

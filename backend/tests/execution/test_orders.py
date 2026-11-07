"""订单状态机与幂等下单。

状态机部分是纯函数断言；幂等部分用计数包装的 paper 源，断言「同 clOrdId
重复提交不再触达交易所」。
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.execution import models, service
from app.execution.core import orders as order_core
from app.execution.errors import ExecutionError
from app.execution.paper import PaperTradingSource
from app.execution.service import submit_order
from tests.execution.conftest import seed_execution_strategy

ZERO = Decimal("0")


def test_legal_transition_chain() -> None:
    sequence = ("pending", "submitted", "partial", "filled")
    current = sequence[0]
    for target in sequence[1:]:
        current = order_core.ensure_transition(current, target)
    assert current == "filled"


def test_legal_terminal_transitions() -> None:
    assert order_core.ensure_transition("pending", "rejected") == "rejected"
    assert order_core.ensure_transition("submitted", "canceled") == "canceled"
    assert order_core.ensure_transition("partial", "canceled") == "canceled"


def test_illegal_transition_raises_without_mutating() -> None:
    with pytest.raises(order_core.OrderStateError) as excinfo:
        order_core.ensure_transition("filled", "partial")
    assert excinfo.value.code == "execution_invalid_transition"
    assert not order_core.can_transition("filled", "partial")


def test_apply_fill_weighted_average() -> None:
    snapshot = order_core.OrderSnapshot(
        state="submitted",
        quantity=Decimal("4"),
        filled_quantity=ZERO,
        average_price=ZERO,
        fee=ZERO,
    )
    first = order_core.apply_fill(
        snapshot, quantity=Decimal("2"), price=Decimal("100"), fee=Decimal("0.5")
    )
    assert first.state == "partial"
    assert first.average_price == Decimal("100")
    second = order_core.apply_fill(
        first, quantity=Decimal("2"), price=Decimal("110"), fee=Decimal("0.5")
    )
    assert second.state == "filled"
    assert second.filled_quantity == Decimal("4")
    assert second.average_price == Decimal("105")
    assert second.fee == Decimal("1.0")


def test_apply_fill_rejects_overfill() -> None:
    snapshot = order_core.OrderSnapshot(
        state="submitted",
        quantity=Decimal("1"),
        filled_quantity=Decimal("0.8"),
        average_price=Decimal("100"),
        fee=ZERO,
    )
    with pytest.raises(order_core.OrderStateError):
        order_core.apply_fill(snapshot, quantity=Decimal("0.3"), price=Decimal("100"))


def test_normalize_unknown_exchange_state_raises() -> None:
    assert order_core.normalize_exchange_state("partially_filled") == "partial"
    with pytest.raises(order_core.OrderStateError):
        order_core.normalize_exchange_state("mystery")


class CountingSource(PaperTradingSource):
    """统计「交易所调用次数」的 paper 源，用来证明幂等没有重复下单。"""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.place_calls = 0
        self.fetch_calls = 0

    async def place_order(self, request):
        self.place_calls += 1
        return await super().place_order(request)

    async def fetch_order(self, **kwargs):
        self.fetch_calls += 1
        return await super().fetch_order(**kwargs)


async def test_duplicate_client_order_id_is_idempotent(session) -> None:
    seeded = await seed_execution_strategy(session)
    source = CountingSource(
        quote_provider=lambda inst_id: _quote(Decimal("100")),
        chunks=(Decimal("1"),),
    )

    body, created = await submit_order(
        session,
        strategy_id=seeded.strategy_id,
        inst_id="BTC-USDT-SWAP",
        side="buy",
        position_side="long",
        quantity=Decimal("1"),
        client_order_id="idem-0001",
        mode="paper",
        source=source,
    )
    assert created is True
    assert body["state"] == "filled"
    assert source.place_calls == 1

    again, created_again = await submit_order(
        session,
        strategy_id=seeded.strategy_id,
        inst_id="BTC-USDT-SWAP",
        side="buy",
        position_side="long",
        quantity=Decimal("1"),
        client_order_id="idem-0001",
        mode="paper",
        source=source,
    )
    assert created_again is False
    assert again["id"] == body["id"]
    assert source.place_calls == 1


async def _quote(value: Decimal) -> Decimal:
    return value


async def test_idempotency_payload_mismatch_is_rejected(session) -> None:
    seeded = await seed_execution_strategy(session)
    source = CountingSource(
        quote_provider=lambda inst_id: _quote(Decimal("100")),
        chunks=(Decimal("1"),),
    )
    await submit_order(
        session,
        strategy_id=seeded.strategy_id,
        inst_id="BTC-USDT-SWAP",
        side="buy",
        position_side="long",
        quantity=Decimal("1"),
        client_order_id="idem-0002",
        mode="paper",
        source=source,
    )

    with pytest.raises(ExecutionError) as excinfo:
        await submit_order(
            session,
            strategy_id=seeded.strategy_id,
            inst_id="BTC-USDT-SWAP",
            side="buy",
            position_side="long",
            quantity=Decimal("2"),
            client_order_id="idem-0002",
            mode="paper",
            source=source,
        )
    assert excinfo.value.code == "execution_idempotency_conflict"
    assert excinfo.value.status_code == 409
    assert source.place_calls == 1


async def test_insert_order_once_handles_unique_conflict(session) -> None:
    seeded = await seed_execution_strategy(session)
    instrument_id = seeded.instrument_ids["BTC-USDT-SWAP"]

    def _order() -> models.Order:
        return models.Order(
            client_order_id="dup-1",
            mode="paper",
            strategy_id=seeded.strategy_id,
            instrument_id=instrument_id,
            inst_id="BTC-USDT-SWAP",
            side="buy",
            position_side="long",
            order_type="market",
            quantity=Decimal("1"),
            reduce_only=False,
            intent="entry",
            state="pending",
            filled_quantity=ZERO,
            fee=ZERO,
        )

    assert await service.insert_order_once(session, _order()) is True
    # 并发同 key：唯一约束冲突返回 False，调用方回查既有单，不抛 500。
    assert await service.insert_order_once(session, _order()) is False
    rows = list((await session.execute(select(models.Order))).scalars())
    assert len(rows) == 1


async def test_reduce_only_over_close_rejected_before_venue(session) -> None:
    """超量平仓必须在落库/撮合之前拒绝，不能留下僵尸单污染对账与恢复。"""

    from app.execution import paper as paper_module
    from app.execution import reconcile as reconcile_module
    from app.execution import recovery as recovery_module

    seeded = await seed_execution_strategy(session)
    entry, _ = await submit_order(
        session,
        strategy_id=seeded.strategy_id,
        inst_id="BTC-USDT-SWAP",
        side="buy",
        position_side="long",
        quantity=Decimal("1"),
        client_order_id="entry-over",
        mode="paper",
    )
    if entry["state"] != "filled":
        entry = await service.poll_order(session, entry["id"])
    assert entry["filled_quantity"] == "1"

    with pytest.raises(ExecutionError) as excinfo:
        await submit_order(
            session,
            strategy_id=seeded.strategy_id,
            inst_id="BTC-USDT-SWAP",
            side="sell",
            position_side="long",
            quantity=Decimal("5"),
            reduce_only=True,
            intent="exit",
            client_order_id="over-close",
            mode="paper",
        )
    assert excinfo.value.code == "execution_position_inconsistent"
    assert excinfo.value.status_code == 409
    assert excinfo.value.details == {
        "requested": "5",
        "available": "1",
        "inst_id": "BTC-USDT-SWAP",
        "position_side": "long",
    }

    rows = list((await session.execute(select(models.Order))).scalars())
    assert [row.client_order_id for row in rows] == ["entry-over"]

    venue = paper_module.get_paper_source()
    assert len(await venue.fetch_positions()) == 1
    reconciled = await reconcile_module.run(session, source=venue)
    assert reconciled["open_diffs"] == 0

    recovered = await recovery_module.run(session)
    assert recovered["mode"] == "paper"
    assert recovered["reconcile"]["open_diffs"] == 0

"""订单与持仓同步：两个方向、部分成交与成交金额补齐。

判据来源（MKACG-731）：

- 本地有单、上游无单 → 本地订单按上游事实置 `failed`。
- 上游有单、本地无单 → 本地补出订单与成交记录。
- 三次部分成交后本地持仓数量等于三次之和（2 + 2 + 2 = 6），成交金额按手算值断言。
- 重复同步不会把同一笔成交加两次。
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.core import Order as VenueOrder
from app.execution import (
    STATUS_FAILED,
    STATUS_FILLED,
    STATUS_OPEN,
    STATUS_PARTIALLY_FILLED,
    ExecutionState,
    Order,
    PositionBook,
    VenueSnapshot,
    from_venue_order,
    sync_state,
)
from app.instrument import Instrument
from tests.execution.conftest import (
    FROZEN_NOW,
    SPOT_INST_ID,
    make_fill,
)

ZERO = Decimal(0)
SYNCED_AT = FROZEN_NOW + timedelta(minutes=1)


def _order(
    *,
    client_order_id: str = "cid1",
    order_id: str = "ord1",
    qty: str = "8",
    filled_qty: str = "0",
    status: str = STATUS_OPEN,
) -> Order:
    return Order(
        client_order_id=client_order_id,
        inst_id=SPOT_INST_ID,
        side="buy",
        order_type="market",
        qty=Decimal(qty),
        price=None,
        created_at=FROZEN_NOW,
        updated_at=FROZEN_NOW,
        order_id=order_id,
        status=status,
        filled_qty=Decimal(filled_qty),
    )


def _three_partial_fills() -> tuple:
    """2 + 2 + 2 股，成交价依次是 100、101、102。"""

    return (
        make_fill(
            order_id="ord1",
            qty="2",
            price="100",
            fill_id="fill-1",
            ts=FROZEN_NOW + timedelta(seconds=1),
        ),
        make_fill(
            order_id="ord1",
            qty="2",
            price="101",
            fill_id="fill-2",
            ts=FROZEN_NOW + timedelta(seconds=2),
        ),
        make_fill(
            order_id="ord1",
            qty="2",
            price="102",
            fill_id="fill-3",
            ts=FROZEN_NOW + timedelta(seconds=3),
        ),
    )


def _paper_positions(spot_instrument: Instrument, fills: tuple) -> tuple:
    """用 paper 账本按成交逐笔记账；持仓数量应等于三次成交量之和。"""

    book = PositionBook()
    for fill in fills:
        book.apply(fill, spot_instrument)
    return book.positions()


def test_local_order_missing_at_the_venue_is_marked_failed() -> None:
    local = _order(status=STATUS_OPEN)

    result = sync_state(
        ExecutionState(orders=(local,)),
        VenueSnapshot(orders=(), fills=(), positions=()),
        now=SYNCED_AT,
    )

    (order,) = result.state.orders
    assert order.status == STATUS_FAILED
    assert order.filled_qty == ZERO
    assert result.failed_client_order_ids == ("cid1",)
    assert result.added_client_order_ids == ()


def test_venue_order_unknown_locally_is_added_with_partial_fills(
    spot_instrument: Instrument,
) -> None:
    """手算：成交量 2 + 2 + 2 = 6；成交金额 200 + 202 + 204 = 606；均价 606 / 6 = 101。"""

    fills = _three_partial_fills()
    venue_order = _order(
        qty="8",
        filled_qty="6",
        status=STATUS_PARTIALLY_FILLED,
    )
    positions = _paper_positions(spot_instrument, fills)

    result = sync_state(
        ExecutionState(),
        VenueSnapshot(orders=(venue_order,), fills=fills, positions=positions),
        now=SYNCED_AT,
    )

    (order,) = result.state.orders
    assert order.status == STATUS_PARTIALLY_FILLED
    assert order.filled_qty == Decimal("6")
    assert order.filled_cost == Decimal("606")
    assert order.avg_fill_price == Decimal("606") / Decimal("6")
    assert len(result.state.fills) == 3
    assert result.added_client_order_ids == ("cid1",)
    assert result.updated_client_order_ids == ()

    (position,) = result.state.positions
    assert position.qty == Decimal("6")
    assert position.qty == Decimal("2") + Decimal("2") + Decimal("2")
    assert position.avg_cost == Decimal("606") / Decimal("6")


def test_venue_order_without_a_client_key_gets_a_stable_local_one() -> None:
    """交易所侧手工下的单没有 `clOrdId`：用订单号派生本地键，重复同步不新增第二条。"""

    venue_order = _order()
    object.__setattr__(venue_order, "client_order_id", "")

    first = sync_state(
        ExecutionState(),
        VenueSnapshot(orders=(venue_order,), fills=(), positions=None),
        now=SYNCED_AT,
    )
    second = sync_state(
        first.state,
        VenueSnapshot(orders=(venue_order,), fills=(), positions=None),
        now=SYNCED_AT,
    )

    (order,) = second.state.orders
    assert order.client_order_id == "xord1"
    assert second.added_client_order_ids == ()


def test_sync_is_idempotent_and_does_not_double_count_fills(
    spot_instrument: Instrument,
) -> None:
    fills = _three_partial_fills()
    venue_order = _order(
        qty="8",
        filled_qty="6",
        status=STATUS_PARTIALLY_FILLED,
    )
    snapshot = VenueSnapshot(
        orders=(venue_order,),
        fills=fills,
        positions=_paper_positions(spot_instrument, fills),
    )

    first = sync_state(ExecutionState(), snapshot, now=SYNCED_AT)
    second = sync_state(
        first.state,
        snapshot,
        now=SYNCED_AT + timedelta(minutes=1),
    )

    (order,) = second.state.orders
    assert order.filled_qty == Decimal("6")
    assert order.filled_cost == Decimal("606")
    assert len(second.state.fills) == 3
    assert second.added_client_order_ids == ()


def test_sync_corrects_a_locally_failed_order_when_the_venue_has_it() -> None:
    """超时后本地先落 failed；上游其实有单，同步按上游事实补回成交。"""

    local = _order(status=STATUS_FAILED)
    fills = _three_partial_fills()
    venue_order = _order(
        qty="8",
        filled_qty="6",
        status=STATUS_PARTIALLY_FILLED,
    )

    result = sync_state(
        ExecutionState(orders=(local,)),
        VenueSnapshot(orders=(venue_order,), fills=fills, positions=None),
        now=SYNCED_AT,
    )

    (order,) = result.state.orders
    assert order.status == STATUS_PARTIALLY_FILLED
    assert order.filled_qty == Decimal("6")
    assert order.filled_cost == Decimal("606")
    assert result.updated_client_order_ids == ("cid1",)


def test_fully_filled_venue_order_requires_the_whole_quantity() -> None:
    """上游已经全部成交、但成交明细只回了一部分：数量按上游对齐，金额只记已知部分。

    这时成交均价的分母是上游全部成交量、分子只有已知金额，因此不在这里断言它。
    """

    venue_order = _order(
        qty="8",
        filled_qty="8",
        status=STATUS_FILLED,
    )
    (fill,) = _three_partial_fills()[:1]

    result = sync_state(
        ExecutionState(),
        VenueSnapshot(orders=(venue_order,), fills=(fill,), positions=None),
        now=SYNCED_AT,
    )

    (order,) = result.state.orders
    assert order.status == STATUS_FILLED
    assert order.filled_qty == Decimal("8")
    assert order.filled_cost == Decimal("200")


def test_sync_fills_in_cost_and_average_price_for_a_normalized_live_order() -> None:
    """T5.2 遗留：`from_venue_order` 只有成交量、金额为 0；同步按成交记录补齐。"""

    venue_order = from_venue_order(
        VenueOrder(
            order_id="ord1",
            client_order_id="cid1",
            inst_id=SPOT_INST_ID,
            side="buy",
            order_type="market",
            qty=Decimal("8"),
            price=None,
            filled_qty=Decimal("6"),
            status="partially_filled",
            ts=FROZEN_NOW,
        )
    )
    assert venue_order.filled_cost == ZERO
    assert venue_order.avg_fill_price is None

    result = sync_state(
        ExecutionState(orders=(venue_order,)),
        VenueSnapshot(orders=(venue_order,), fills=_three_partial_fills(), positions=None),
        now=SYNCED_AT,
    )

    (order,) = result.state.orders
    assert order.filled_qty == Decimal("6")
    assert order.filled_cost == Decimal("606")
    assert order.avg_fill_price == Decimal("101")

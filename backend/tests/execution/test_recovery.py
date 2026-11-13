"""重启后的状态恢复：未完成订单与部分成交以交易所快照为准重建。

判据来源（MKACG-736）：

- 重启后本地状态为空，交易所侧仍有一张部分成交的订单：恢复后只有这一条订单，
  已成交量是各笔成交之和，状态是「部分成交」。
- 同一个快照恢复两次不会把成交加两次，也不会多出一条订单。
- 恢复只做状态收敛，不产生新订单。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.core import Fill
from app.execution import (
    STATUS_OPEN,
    STATUS_PARTIALLY_FILLED,
    ExecutionState,
    Order,
    VenueSnapshot,
    recover_state,
)
from app.execution.orders import STATUS_CANCELLED
from app.execution.positions import NET_POS_SIDE, AccountPosition
from tests.execution.conftest import (
    FROZEN_NOW,
    PRODUCT_KEY,
    SWAP,
    SWAP_INST_ID,
    make_fill,
)

D = Decimal
NOW = datetime(2026, 11, 12, 3, 10, 0, tzinfo=UTC)


def _venue_order(
    *,
    status: str = STATUS_PARTIALLY_FILLED,
    filled_qty: str = "3",
) -> Order:
    return Order(
        client_order_id="p6buy1",
        inst_id=SWAP_INST_ID,
        side="buy",
        order_type="limit",
        qty=D("5"),
        price=D("100"),
        created_at=FROZEN_NOW,
        updated_at=FROZEN_NOW,
        order_id="ord1",
        pos_side=NET_POS_SIDE,
        status=status,
        filled_qty=D(filled_qty),
        filled_cost=D(filled_qty) * D("100"),
    )


def _fills() -> tuple[Fill, ...]:
    return (
        make_fill(
            order_id="ord1",
            inst_id=SWAP_INST_ID,
            qty="2",
            price="100",
            fill_id="trade1",
        ),
        make_fill(
            order_id="ord1",
            inst_id=SWAP_INST_ID,
            qty="1",
            price="100",
            fill_id="trade2",
        ),
    )


def _position() -> AccountPosition:
    return AccountPosition(
        product_key=PRODUCT_KEY,
        inst_type=SWAP,
        side="long",
        qty=D("3"),
        avg_cost=D("100"),
        pos_side=NET_POS_SIDE,
    )


def test_partial_fill_is_accumulated_and_left_as_an_unfinished_order() -> None:
    """两笔部分成交 2 + 1：恢复后成交量 3、状态部分成交、订单只有一条。"""

    result = recover_state(
        ExecutionState(),
        VenueSnapshot(
            orders=(_venue_order(),),
            fills=_fills(),
            positions=(_position(),),
        ),
        now=NOW,
    )

    assert len(result.state.orders) == 1
    (order,) = result.state.orders
    assert order.status == STATUS_PARTIALLY_FILLED
    assert order.filled_qty == D("3")
    assert order.filled_cost == D("300")
    assert result.unfinished_orders == (order,)
    assert result.partial_orders == (order,)
    assert {fill.fill_id for fill in result.new_fills} == {"trade1", "trade2"}
    assert result.state.positions == (_position(),)


def test_recovering_twice_does_not_double_count_fills_or_duplicate_orders() -> None:
    """同一个快照再恢复一次：没有新成交、订单数仍是一条、已成交量不变。"""

    snapshot = VenueSnapshot(
        orders=(_venue_order(),),
        fills=_fills(),
        positions=(_position(),),
    )
    first = recover_state(ExecutionState(), snapshot, now=NOW)
    second = recover_state(first.state, snapshot, now=NOW)

    assert second.new_fills == ()
    assert len(second.state.orders) == 1
    assert second.state.orders[0].filled_qty == D("3")
    assert second.state.orders[0].order_id == "ord1"


def test_restart_rebuilds_an_untouched_open_order_from_the_venue() -> None:
    """重启后本地什么都没有：交易所侧一张未成交的挂单仍被恢复成未完成订单。"""

    result = recover_state(
        ExecutionState(),
        VenueSnapshot(
            orders=(_venue_order(status=STATUS_OPEN, filled_qty="0"),),
            fills=(),
            positions=(_position(),),
        ),
        now=NOW,
    )

    (order,) = result.state.orders
    assert order.status == STATUS_OPEN
    assert order.filled_qty == D("0")
    assert result.unfinished_orders == (order,)
    assert result.partial_orders == ()
    assert result.new_fills == ()


def test_cancelled_order_is_not_reported_as_unfinished() -> None:
    """交易所已撤单：恢复后仍是终态，不进入未完成订单清单。"""

    result = recover_state(
        ExecutionState(),
        VenueSnapshot(
            orders=(_venue_order(status=STATUS_CANCELLED, filled_qty="0"),),
            fills=(),
            positions=(),
        ),
        now=NOW,
    )

    (order,) = result.state.orders
    assert order.status == STATUS_CANCELLED
    assert result.unfinished_orders == ()
    assert result.partial_orders == ()

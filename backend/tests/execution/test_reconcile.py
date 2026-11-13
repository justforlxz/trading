"""对账差额清单：只比较形状、只读、不抹平。

判据来源（MKACG-736）：

- 两类持仓（SWAP 读持仓接口、SPOT 由余额推导）产出同一种形状，比较时不判断类别。
- 差额与百分比是纯函数，手算值写进用例；虚拟侧为 0 时百分比是「无定义」而不是 0。
- 成因按证据归类：部分成交、未同步成交、人工干预、交易所侧未知。
- 对账不改任何一侧的数量与成本。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.core import Fill
from app.execution import (
    NET_POS_SIDE,
    SIDE_LONG,
    STATUS_FILLED,
    STATUS_PARTIALLY_FILLED,
    AccountPosition,
    Order,
    ReconcileHolding,
    reconcile_positions,
)
from app.instrument import Instrument
from tests.execution.conftest import (
    FROZEN_NOW,
    PRODUCT_KEY,
    SPOT,
    SPOT_INST_ID,
    SWAP,
    make_fill,
)

D = Decimal
AS_OF = datetime(2026, 11, 12, 3, 5, 0, tzinfo=UTC)
ZERO = D(0)


def _actual(
    *,
    product_key: str = PRODUCT_KEY,
    inst_type: str = SPOT,
    side: str = SIDE_LONG,
    qty: str = "10",
    avg_cost: str = "100",
    pos_side: str | None = None,
) -> AccountPosition:
    return AccountPosition(
        product_key=product_key,
        inst_type=inst_type,
        side=side,
        qty=D(qty),
        avg_cost=D(avg_cost),
        pos_side=pos_side,
    )


def _holding(
    *,
    product_key: str = PRODUCT_KEY,
    inst_type: str = SPOT,
    side: str = SIDE_LONG,
    qty: str = "10",
    avg_cost: str = "100",
) -> ReconcileHolding:
    return ReconcileHolding(
        product_key=product_key,
        inst_type=inst_type,
        side=side,
        qty=D(qty),
        avg_cost=D(avg_cost),
    )


def test_matching_spot_and_swap_positions_produce_an_empty_report() -> None:
    """SPOT 与 SWAP 各一条且两侧一致：差额清单为空，比较不按类别分叉。"""

    actual = (
        _actual(inst_type=SPOT, qty="3", avg_cost="350"),
        _actual(inst_type=SWAP, qty="2", avg_cost="99.5", pos_side=NET_POS_SIDE),
    )
    virtual = (
        _holding(inst_type=SPOT, qty="3", avg_cost="350"),
        _holding(inst_type=SWAP, qty="2", avg_cost="99.5"),
    )

    report = reconcile_positions(actual, virtual, as_of=AS_OF)

    assert report.differences == ()
    assert report.balanced is True
    assert report.checked_products == (PRODUCT_KEY,)


def test_quantity_difference_has_hand_computed_value_and_percentage() -> None:
    """手算：实际 12、虚拟 10 → 差额 2、百分比 20%。"""

    report = reconcile_positions(
        (_actual(qty="12", avg_cost="100"),),
        (_holding(qty="10", avg_cost="100"),),
        as_of=AS_OF,
    )

    (item,) = report.differences
    assert item.product_key == PRODUCT_KEY
    assert item.side == SIDE_LONG
    assert item.actual_qty == D("12")
    assert item.virtual_qty == D("10")
    assert item.actual_avg_cost == D("100")
    assert item.virtual_avg_cost == D("100")
    assert item.qty_diff == D("2")
    assert item.qty_diff_pct == D("20")
    assert item.as_of == AS_OF


def test_negative_difference_and_undefined_percentage_are_both_reported() -> None:
    """手算：实际 8、虚拟 10 → 差额 -2、百分比 -20%；虚拟为 0 时百分比无定义。"""

    negative = reconcile_positions(
        (_actual(qty="8"),),
        (_holding(qty="10"),),
        as_of=AS_OF,
    ).differences[0]
    assert negative.qty_diff == D("-2")
    assert negative.qty_diff_pct == D("-20")

    missing = reconcile_positions(
        (_actual(qty="3"),),
        (),
        as_of=AS_OF,
    ).differences[0]
    assert missing.virtual_qty == ZERO
    assert missing.virtual_avg_cost is None
    assert missing.qty_diff == D("3")
    assert missing.qty_diff_pct is None


def test_cost_only_difference_is_listed_as_manual_intervention() -> None:
    """数量相同、成本不同也是差额：两侧都在、没有订单证据 → 人工干预。"""

    report = reconcile_positions(
        (_actual(qty="10", avg_cost="105"),),
        (_holding(qty="10", avg_cost="100"),),
        as_of=AS_OF,
    )

    (item,) = report.differences
    assert item.qty_diff == ZERO
    assert item.qty_diff_pct == ZERO
    assert item.cause == "manual_intervention"


def test_spot_cost_zero_is_unknown_not_a_cost_difference() -> None:
    """现货上游没下发成本时记 0 表示未知；不能拿它和虚拟成本比出一个假差额。"""

    report = reconcile_positions(
        (_actual(inst_type=SPOT, qty="3", avg_cost="0"),),
        (_holding(inst_type=SPOT, qty="3", avg_cost="350"),),
        as_of=AS_OF,
    )

    assert report.differences == ()
    assert report.balanced is True


def test_partial_fill_is_classified_as_partial_fill() -> None:
    """交易所部分成交、虚拟账本还没记：成因是部分成交。"""

    order = Order(
        client_order_id="p6buy1",
        inst_id=SPOT_INST_ID,
        side="buy",
        order_type="limit",
        qty=D("5"),
        price=D("100"),
        created_at=FROZEN_NOW,
        updated_at=FROZEN_NOW,
        order_id="ord1",
        status=STATUS_PARTIALLY_FILLED,
        filled_qty=D("2"),
        filled_cost=D("200"),
    )

    report = reconcile_positions(
        (_actual(qty="2", avg_cost="100"),),
        (),
        as_of=AS_OF,
        orders=(order,),
        instruments=(_instrument_view(),),
    )

    (item,) = report.differences
    assert item.cause == "partial_fill"


def test_unapplied_fill_is_classified_as_unsynced_fill() -> None:
    """订单已全部成交、成交记录已经取到但还没记进虚拟账本：成因是未同步成交。"""

    order = Order(
        client_order_id="p6buy1",
        inst_id=SPOT_INST_ID,
        side="buy",
        order_type="market",
        qty=D("2"),
        price=None,
        created_at=FROZEN_NOW,
        updated_at=FROZEN_NOW,
        order_id="ord1",
        status=STATUS_FILLED,
        filled_qty=D("2"),
        filled_cost=D("200"),
    )
    fill: Fill = make_fill(order_id="ord1", qty="2", price="100")

    report = reconcile_positions(
        (_actual(qty="2", avg_cost="100"),),
        (),
        as_of=AS_OF,
        orders=(order,),
        unapplied_fills=(fill,),
        instruments=(_instrument_view(),),
    )

    (item,) = report.differences
    assert item.cause == "unsynced_fill"


def test_terminal_partial_fill_does_not_mask_unsynced_fill() -> None:
    """已撤单但只成交一部分：订单已经结束，差额应归为未同步成交而不是部分成交。"""

    order = Order(
        client_order_id="p6buy1",
        inst_id=SPOT_INST_ID,
        side="buy",
        order_type="limit",
        qty=D("5"),
        price=D("100"),
        created_at=FROZEN_NOW,
        updated_at=FROZEN_NOW,
        order_id="ord1",
        status="cancelled",
        filled_qty=D("2"),
        filled_cost=D("200"),
    )
    fill: Fill = make_fill(order_id="ord1", qty="2", price="100")

    report = reconcile_positions(
        (_actual(qty="2", avg_cost="100"),),
        (),
        as_of=AS_OF,
        orders=(order,),
        unapplied_fills=(fill,),
        instruments=(_instrument_view(),),
    )

    (item,) = report.differences
    assert item.cause == "unsynced_fill"


def test_terminal_partial_fill_without_fill_evidence_is_not_partial_fill() -> None:
    """终态部分成交订单本身不构成「订单还没走完」的证据。"""

    order = Order(
        client_order_id="p6buy1",
        inst_id=SPOT_INST_ID,
        side="buy",
        order_type="limit",
        qty=D("5"),
        price=D("100"),
        created_at=FROZEN_NOW,
        updated_at=FROZEN_NOW,
        order_id="ord1",
        status="cancelled",
        filled_qty=D("2"),
        filled_cost=D("200"),
    )

    report = reconcile_positions(
        (_actual(qty="2", avg_cost="100"),),
        (_holding(qty="1", avg_cost="100"),),
        as_of=AS_OF,
        orders=(order,),
        instruments=(_instrument_view(),),
    )

    (item,) = report.differences
    assert item.cause == "manual_intervention"


def test_one_sided_position_without_records_is_exchange_side_unknown() -> None:
    """只有交易所侧的数量、没有任何本地订单或成交可解释：交易所侧未知。"""

    report = reconcile_positions(
        (_actual(qty="2"),),
        (),
        as_of=AS_OF,
        instruments=(_instrument_view(),),
    )

    (item,) = report.differences
    assert item.cause == "exchange_side_unknown"


def test_reconcile_is_read_only() -> None:
    """对账前后两侧数量与成本逐字段相同：只产出清单，不修正。"""

    actual = [_actual(qty="12", avg_cost="100")]
    virtual = [_holding(qty="10", avg_cost="100")]
    actual_before = tuple(actual)
    virtual_before = tuple(virtual)

    reconcile_positions(tuple(actual), tuple(virtual), as_of=AS_OF)

    assert tuple(actual) == actual_before
    assert tuple(virtual) == virtual_before


def test_spot_and_swap_forms_of_one_product_aggregate_before_comparison() -> None:
    """手算：现货 3 + 永续 2 = 5；虚拟侧同样 5，差额为空，不按类别重复计算。"""

    report = reconcile_positions(
        (
            _actual(inst_type=SPOT, qty="3", avg_cost="350"),
            _actual(inst_type=SWAP, qty="2", avg_cost="99.5", pos_side=NET_POS_SIDE),
        ),
        (
            _holding(inst_type=SPOT, qty="3", avg_cost="350"),
            _holding(inst_type=SWAP, qty="2", avg_cost="99.5"),
        ),
        as_of=AS_OF,
    )

    assert report.differences == ()


def _instrument_view() -> Instrument:
    return Instrument(
        symbol=SPOT_INST_ID,
        inst_type=SPOT,
        product_key=PRODUCT_KEY,
        asset_type="tokenized_equity",
        exchange="okx",
        base_currency=PRODUCT_KEY,
        quote_currency="USDT",
        tick_size=D("0.01"),
        lot_size=D("0.001"),
        min_order_size=D("0.001"),
        trading_status="live",
    )

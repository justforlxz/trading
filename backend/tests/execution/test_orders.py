"""订单状态机与部分成交累加：转移表逐边覆盖 + 已知答案。

判据来源（MKACG-730）：

- 参数化覆盖全部合法转移与全部非法转移；非法转移抛 `ValidationError`。
- 三次部分成交后数量等于三次之和，金额按成交量加权（手算值写进断言）。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core import ValidationError
from app.execution import (
    LEGAL_TRANSITIONS,
    ORDER_STATUSES,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_FILLED,
    STATUS_OPEN,
    STATUS_PARTIALLY_FILLED,
    STATUS_PENDING,
    TERMINAL_STATUSES,
    Order,
    accept,
    apply_fill,
    cancel,
    fail,
    new_order,
    require_transition,
)
from tests.execution.conftest import FROZEN_NOW, SPOT_INST_ID, make_fill, make_intent

ZERO = Decimal(0)
NOW = FROZEN_NOW
STATUSES = tuple(sorted(ORDER_STATUSES))


def _accepted(*, qty: str = "3") -> Order:
    return accept(new_order(make_intent(qty=qty), now=NOW), "paper0001", now=NOW)


# ------------------------------------------------------------------ 状态机：全边覆盖


@pytest.mark.parametrize(
    ("current", "target"),
    [(current, target) for current in STATUSES for target in sorted(LEGAL_TRANSITIONS[current])],
)
def test_every_legal_transition_is_accepted(current: str, target: str) -> None:
    require_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (current, target)
        for current in STATUSES
        for target in STATUSES
        if target not in LEGAL_TRANSITIONS[current]
    ],
)
def test_every_illegal_transition_raises_validation_error(current: str, target: str) -> None:
    with pytest.raises(ValidationError):
        require_transition(current, target)


def test_transition_table_is_the_single_source_of_statuses() -> None:
    """状态集合与转移表的键完全一致：加状态必须同时加一行转移。"""

    assert set(LEGAL_TRANSITIONS) == ORDER_STATUSES
    assert {
        STATUS_PENDING,
        STATUS_OPEN,
        STATUS_PARTIALLY_FILLED,
        STATUS_FILLED,
        STATUS_CANCELLED,
        STATUS_FAILED,
    } == ORDER_STATUSES


#: 字面写下来的期望转移表。故意不引用 `LEGAL_TRANSITIONS` 自身：合法边与非法边两条
#: 用例都由转移表展开，表被改错（例如允许 `pending → filled`）时它们会跟着一起错，
#: 只有把期望边另写一份，才能证伪「转移表写错了」。
EXPECTED_EDGES: dict[str, set[str]] = {
    STATUS_PENDING: {STATUS_OPEN, STATUS_CANCELLED, STATUS_FAILED},
    STATUS_OPEN: {STATUS_PARTIALLY_FILLED, STATUS_FILLED, STATUS_CANCELLED, STATUS_FAILED},
    STATUS_PARTIALLY_FILLED: {
        STATUS_PARTIALLY_FILLED,
        STATUS_FILLED,
        STATUS_CANCELLED,
        STATUS_FAILED,
    },
    STATUS_FILLED: set(),
    STATUS_CANCELLED: set(),
    STATUS_FAILED: set(),
}


def test_transition_table_matches_the_written_down_edges() -> None:
    """逐边对照字面期望表：多一条、少一条都要红。"""

    actual = {status: set(targets) for status, targets in LEGAL_TRANSITIONS.items()}

    assert actual == EXPECTED_EDGES


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES))
def test_terminal_statuses_have_no_outgoing_edges(status: str) -> None:
    assert LEGAL_TRANSITIONS[status] == frozenset()


def test_unknown_status_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        require_transition(STATUS_PENDING, "unknown")
    with pytest.raises(ValidationError):
        require_transition("unknown", STATUS_OPEN)


# ------------------------------------------------------------------ 订单生命周期


def test_new_order_is_pending_without_a_venue_order_id() -> None:
    order = new_order(make_intent(qty="3"), now=NOW)

    assert order.status == STATUS_PENDING
    assert order.order_id == ""
    assert order.filled_qty == ZERO
    assert order.avg_fill_price is None
    assert order.remaining_qty == Decimal("3")


def test_accept_moves_pending_to_open_and_records_the_venue_order_id() -> None:
    order = accept(new_order(make_intent(), now=NOW), "ord-1", now=NOW)

    assert order.status == STATUS_OPEN
    assert order.order_id == "ord-1"


def test_fill_before_acceptance_is_rejected() -> None:
    """成交必须先受理：`pending → partially_filled` 不在转移表里。"""

    order = new_order(make_intent(qty="2"), now=NOW)

    with pytest.raises(ValidationError):
        apply_fill(order, make_fill(qty="2", price="100"), now=NOW)


def test_cancel_keeps_the_filled_part_instead_of_resetting_it() -> None:
    order = apply_fill(_accepted(), make_fill(qty="1", price="100"), now=NOW)

    cancelled = cancel(order, now=NOW)

    assert cancelled.status == STATUS_CANCELLED
    assert cancelled.filled_qty == Decimal("1")
    assert cancelled.filled_cost == Decimal("100")
    assert cancelled.remaining_qty == Decimal("2")


def test_fail_keeps_the_filled_part_instead_of_resetting_it() -> None:
    order = apply_fill(_accepted(), make_fill(qty="1", price="100"), now=NOW)

    failed = fail(order, now=NOW)

    assert failed.status == STATUS_FAILED
    assert failed.filled_qty == Decimal("1")


def test_terminal_order_rejects_further_transitions() -> None:
    filled = apply_fill(_accepted(), make_fill(qty="3", price="100"), now=NOW)

    assert filled.status == STATUS_FILLED
    with pytest.raises(ValidationError):
        cancel(filled, now=NOW)
    with pytest.raises(ValidationError):
        fail(filled, now=NOW)


# ---------------------------------------------------------------- 部分成交累加


def test_three_partial_fills_accumulate_quantity_and_weighted_cost() -> None:
    """手算：数量 10+10+5=25；金额 10×100 + 10×103 + 5×107 = 1000+1030+535 = 2565。

    加权均价 2565 / 25 = 102.6。覆盖式写法（最后一笔把前几笔抹掉）会得到 5 与 107，
    本用例因此能证伪「覆盖而不是累加」。
    """

    order = _accepted(qty="30")

    order = apply_fill(order, make_fill(fill_id="f1", qty="10", price="100"), now=NOW)
    assert (order.status, order.filled_qty) == (STATUS_PARTIALLY_FILLED, Decimal("10"))

    order = apply_fill(order, make_fill(fill_id="f2", qty="10", price="103"), now=NOW)
    order = apply_fill(order, make_fill(fill_id="f3", qty="5", price="107"), now=NOW)

    assert order.filled_qty == Decimal("25")
    assert order.filled_cost == Decimal("2565")
    assert order.avg_fill_price == Decimal("102.6")
    assert order.status == STATUS_PARTIALLY_FILLED


def test_the_last_partial_fill_closes_the_order() -> None:
    order = _accepted(qty="30")
    for fill in (
        make_fill(fill_id="f1", qty="10", price="100"),
        make_fill(fill_id="f2", qty="10", price="103"),
        make_fill(fill_id="f3", qty="5", price="107"),
    ):
        order = apply_fill(order, fill, now=NOW)

    order = apply_fill(order, make_fill(fill_id="f4", qty="5", price="99"), now=NOW)

    assert order.status == STATUS_FILLED
    assert order.filled_qty == Decimal("30")
    assert order.filled_cost == Decimal("2565") + Decimal("5") * Decimal("99")
    assert order.remaining_qty == ZERO


def test_overfill_is_rejected_and_the_order_is_untouched() -> None:
    order = _accepted(qty="3")

    with pytest.raises(ValidationError):
        apply_fill(order, make_fill(qty="4", price="100"), now=NOW)

    assert order.filled_qty == ZERO


def test_non_positive_fill_is_rejected() -> None:
    order = _accepted(qty="3")

    with pytest.raises(ValidationError):
        apply_fill(order, make_fill(qty="0", price="100"), now=NOW)
    with pytest.raises(ValidationError):
        apply_fill(order, make_fill(qty="1", price="0"), now=NOW)


@pytest.mark.parametrize(
    "fill_kwargs",
    [
        {"inst_id": "AAPL-USDT-SWAP"},
        {"side": "sell"},
        {"order_id": "another-order"},
    ],
    ids=["别的标的", "别的方向", "别的订单号"],
)
def test_fill_must_belong_to_the_order(fill_kwargs: dict[str, str]) -> None:
    order = _accepted(qty="3")

    with pytest.raises(ValidationError):
        apply_fill(order, make_fill(qty="1", price="100", **fill_kwargs), now=NOW)


# ------------------------------------------------------------- 构造期自洽性校验


@pytest.mark.parametrize(
    "kwargs",
    [
        {"order_type": "limit", "price": None},
        {"order_type": "market", "price": Decimal("100")},
        {"qty": ZERO, "price": None, "order_type": "market"},
        {"filled_qty": Decimal("-1")},
        {"filled_qty": Decimal("4")},
        {"status": STATUS_FILLED},
        {"status": STATUS_PENDING, "filled_qty": Decimal("1"), "filled_cost": Decimal("100")},
        {"status": STATUS_CANCELLED, "filled_qty": Decimal("3"), "filled_cost": Decimal("300")},
        {"status": "unknown"},
    ],
    ids=[
        "限价单缺价格",
        "市价单给了价格",
        "数量为 0",
        "成交量为负",
        "成交量超过订单量",
        "状态是 filled 但没成交满",
        "状态是 pending 却有成交",
        "状态是 cancelled 却成交满了",
        "未知状态",
    ],
)
def test_inconsistent_orders_cannot_be_constructed(kwargs: dict[str, object]) -> None:
    fields: dict[str, object] = {
        "client_order_id": "cli1",
        "inst_id": SPOT_INST_ID,
        "side": "buy",
        "order_type": "limit",
        "qty": Decimal("3"),
        "price": Decimal("100"),
        "created_at": NOW,
        "updated_at": NOW,
    }
    fields.update(kwargs)

    with pytest.raises(ValidationError):
        Order(**fields)

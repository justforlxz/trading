"""账户实际持仓：两类同形状、现货四列必须是 `None`、paper 账本记账。

判据来源（MKACG-730）：

- 同一份余额明细推导出的现货持仓，字段集合与永续持仓结果一致。
- `leverage` / `margin` / `liq_price` 在现货上是 `None`，不是 0。
- 类别分叉在 `backend/app/execution` 里只有一处。
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from pathlib import Path

import pytest

from app.core import Money, Position, ValidationError
from app.execution import (
    NET_POS_SIDE,
    SIDE_LONG,
    SIDE_SHORT,
    AccountPosition,
    PaperRejected,
    PositionBook,
    from_venue_position,
)
from app.instrument import Instrument
from tests.execution.conftest import (
    PRODUCT_KEY,
    QUOTE_CURRENCY,
    SPOT,
    SPOT_INST_ID,
    SWAP,
    SWAP_INST_ID,
    make_fill,
)

ZERO = Decimal(0)
BACKEND_ROOT = Path(__file__).resolve().parents[2]
EXECUTION_DIR = BACKEND_ROOT / "app" / "execution"


def _spot_position(qty: str = "3", avg_price: str = "350") -> Position:
    """T5.1 由余额明细推导出的现货持仓形状（数量 = 可用量 + 冻结量）。"""

    return Position(
        inst_id=SPOT_INST_ID,
        qty=Decimal(qty),
        avg_price=Decimal(avg_price),
        unrealized_pnl=Money(Decimal("7"), QUOTE_CURRENCY),
    )


def _swap_position(qty: str = "-2", avg_price: str = "101") -> Position:
    return Position(
        inst_id=SWAP_INST_ID,
        qty=Decimal(qty),
        avg_price=Decimal(avg_price),
        unrealized_pnl=Money(Decimal("-4"), QUOTE_CURRENCY),
    )


def _paper_position(**overrides: object) -> AccountPosition:
    fields: dict[str, object] = {
        "product_key": PRODUCT_KEY,
        "inst_type": SPOT,
        "side": SIDE_LONG,
        "qty": Decimal("1"),
        "avg_cost": Decimal("100"),
    }
    fields.update(overrides)
    return AccountPosition(**fields)


# ------------------------------------------------------------------ 两类同形状


def test_spot_and_swap_positions_share_the_same_field_set(
    spot_instrument: Instrument, swap_instrument: Instrument
) -> None:
    """同一份余额明细推导出的现货持仓与永续持仓接口结果，字段集合完全相同。"""

    spot = from_venue_position(_spot_position(), spot_instrument)
    swap = from_venue_position(
        _swap_position(),
        swap_instrument,
        pos_side=SIDE_SHORT,
        leverage=Decimal("5"),
        margin=Decimal("40.4"),
        liq_price=Decimal("120.2"),
    )

    assert [field.name for field in dataclasses.fields(spot)] == [
        field.name for field in dataclasses.fields(swap)
    ]
    assert spot.inst_type == SPOT
    assert swap.inst_type == SWAP


def test_spot_position_keeps_the_swap_columns_none(
    spot_instrument: Instrument,
) -> None:
    """现货的四个永续专属字段是 `None`：用 0 冒充会被下游当成有效值参与比较。"""

    spot = from_venue_position(_spot_position(), spot_instrument)

    assert spot.pos_side is None
    assert spot.leverage is None
    assert spot.margin is None
    assert spot.liq_price is None


def test_swap_position_keeps_the_reported_columns(swap_instrument: Instrument) -> None:
    swap = from_venue_position(
        _swap_position(),
        swap_instrument,
        pos_side=SIDE_SHORT,
        leverage=Decimal("5"),
        margin=Decimal("40.4"),
        liq_price=Decimal("120.2"),
    )

    assert swap.pos_side == SIDE_SHORT
    assert swap.leverage == Decimal("5")
    assert swap.margin == Decimal("40.4")
    assert swap.liq_price == Decimal("120.2")


@pytest.mark.parametrize(
    "overrides",
    [
        {"pos_side": NET_POS_SIDE},
        {"leverage": ZERO},
        {"margin": ZERO},
        {"liq_price": ZERO},
    ],
    ids=["pos_side", "leverage", "margin", "liq_price"],
)
def test_spot_position_rejects_placeholders_for_the_swap_columns(
    overrides: dict[str, object],
) -> None:
    """现货给这四个字段填 0（或任何值）都不成立：它们只属于永续。"""

    with pytest.raises(ValidationError):
        _paper_position(**overrides)


def test_swap_position_requires_a_position_side(swap_instrument: Instrument) -> None:
    with pytest.raises(ValidationError):
        from_venue_position(_swap_position(), swap_instrument)


# ------------------------------------------------------------ 数量、方向与换算


def test_quantity_sign_becomes_side_plus_absolute_quantity(
    spot_instrument: Instrument, swap_instrument: Instrument
) -> None:
    """上游数量带符号：正数为多、负数为空；本层把符号搬到 `side`，`qty` 只留绝对值。"""

    long_spot = from_venue_position(_spot_position(qty="3"), spot_instrument)
    short_swap = from_venue_position(_swap_position(qty="-2"), swap_instrument, pos_side=SIDE_SHORT)

    assert (long_spot.side, long_spot.qty) == (SIDE_LONG, Decimal("3"))
    assert (short_swap.side, short_swap.qty) == (SIDE_SHORT, Decimal("2"))


def test_zero_quantity_position_is_rejected(spot_instrument: Instrument) -> None:
    """上游本来就不返回无持仓的标的；真出现 0 是上游或适配层的问题，不当成空持仓。"""

    with pytest.raises(ValidationError):
        from_venue_position(_spot_position(qty="0"), spot_instrument)


def test_spot_position_cannot_be_short() -> None:
    """现货只有多头：记一条现货空头只可能来自记错符号或拿错标的，构造期就拒绝。"""

    with pytest.raises(ValidationError):
        _paper_position(side=SIDE_SHORT)


def test_venue_position_must_match_the_instrument_row(swap_instrument: Instrument) -> None:
    """持仓与标的行必须指同一个标的：拿错配对会把 A 的持仓记成 B 的产品键。"""

    with pytest.raises(ValidationError):
        from_venue_position(_spot_position(), swap_instrument)


# ---------------------------------------------------------------- paper 记账


def test_position_book_weights_cost_by_filled_quantity(spot_instrument: Instrument) -> None:
    """手算：2×100 + 1×130 = 330，除以 3 得成本 110。"""

    book = PositionBook()
    book.apply(make_fill(qty="2", price="100"), spot_instrument)
    book.apply(make_fill(fill_id="fill2", qty="1", price="130"), spot_instrument)

    (position,) = book.positions()
    assert (position.side, position.qty, position.avg_cost) == (
        SIDE_LONG,
        Decimal("3"),
        Decimal("110"),
    )


def test_position_book_reduces_quantity_and_keeps_the_cost(spot_instrument: Instrument) -> None:
    book = PositionBook()
    book.apply(make_fill(qty="2", price="100"), spot_instrument)
    book.apply(make_fill(fill_id="fill2", qty="1", price="130"), spot_instrument)

    book.apply(make_fill(fill_id="fill3", side="sell", qty="1", price="140"), spot_instrument)

    (position,) = book.positions()
    assert position.qty == Decimal("2")
    assert position.avg_cost == Decimal("110")


def test_position_book_drops_the_position_when_it_reaches_zero(
    spot_instrument: Instrument,
) -> None:
    book = PositionBook()
    book.apply(make_fill(qty="2", price="100"), spot_instrument)

    book.apply(make_fill(fill_id="fill2", side="sell", qty="2", price="110"), spot_instrument)

    assert book.positions() == ()


def test_position_book_rejects_selling_more_than_held_and_keeps_the_book(
    spot_instrument: Instrument,
) -> None:
    """可减持仓不足时账本必须原样不动：先扣数量再报错会留下一条错账。"""

    book = PositionBook()
    book.apply(make_fill(qty="1", price="100"), spot_instrument)
    before = book.positions()

    with pytest.raises(PaperRejected):
        book.apply(make_fill(fill_id="fill2", side="sell", qty="2", price="100"), spot_instrument)

    assert book.positions() == before


def test_position_book_keeps_long_and_short_legs_apart(swap_instrument: Instrument) -> None:
    """永续对冲模式：同一产品可以同时有多空两条腿，数量与成本各算各的。"""

    book = PositionBook()
    book.apply(
        make_fill(inst_id=SWAP_INST_ID, qty="1", price="100"),
        swap_instrument,
        pos_side=SIDE_LONG,
    )
    book.apply(
        make_fill(fill_id="fill2", inst_id=SWAP_INST_ID, side="sell", qty="2", price="110"),
        swap_instrument,
        pos_side=SIDE_SHORT,
    )

    long_leg, short_leg = book.positions()
    assert (long_leg.side, long_leg.qty, long_leg.pos_side) == (
        SIDE_LONG,
        Decimal("1"),
        SIDE_LONG,
    )
    assert (short_leg.side, short_leg.qty, short_leg.pos_side) == (
        SIDE_SHORT,
        Decimal("2"),
        SIDE_SHORT,
    )


def test_reduce_only_closes_the_opposite_leg_in_one_way_mode(
    swap_instrument: Instrument,
) -> None:
    """单向模式下卖出开空腿、只减仓的买入减的是空腿；持仓方向字段记 `net`。"""

    book = PositionBook()
    book.apply(
        make_fill(inst_id=SWAP_INST_ID, side="sell", qty="2", price="110"),
        swap_instrument,
    )
    (opened,) = book.positions()
    assert (opened.side, opened.pos_side) == (SIDE_SHORT, NET_POS_SIDE)

    book.apply(
        make_fill(fill_id="fill2", inst_id=SWAP_INST_ID, side="buy", qty="1", price="105"),
        swap_instrument,
        reduce_only=True,
    )

    (reduced,) = book.positions()
    assert (reduced.side, reduced.qty) == (SIDE_SHORT, Decimal("1"))


def test_net_mode_reduces_the_existing_leg_before_opening_the_other(
    swap_instrument: Instrument,
) -> None:
    """单向模式：买入 10 后再卖出 5（不带 reduce_only）是减多，不是另开一条空腿。

    同一产品在单向模式下只能有一条腿；按成交方向各自开腿会凭空造出一条空头，
    按产品查持仓、核对交易所、按腿算保证金都会读错。
    """

    book = PositionBook()
    book.apply(make_fill(inst_id=SWAP_INST_ID, qty="10", price="100"), swap_instrument)

    book.apply(
        make_fill(fill_id="fill2", inst_id=SWAP_INST_ID, side="sell", qty="5", price="110"),
        swap_instrument,
    )

    (position,) = book.positions()
    assert (position.side, position.qty, position.avg_cost, position.pos_side) == (
        SIDE_LONG,
        Decimal("5"),
        Decimal("100"),
        NET_POS_SIDE,
    )


def test_net_mode_opens_the_other_leg_only_with_the_remainder(
    swap_instrument: Instrument,
) -> None:
    """手算：多头 10 被卖出 15 平掉后，剩下 5 才成为空头，成本 110。"""

    book = PositionBook()
    book.apply(make_fill(inst_id=SWAP_INST_ID, qty="10", price="100"), swap_instrument)

    book.apply(
        make_fill(fill_id="fill2", inst_id=SWAP_INST_ID, side="sell", qty="15", price="110"),
        swap_instrument,
    )

    (position,) = book.positions()
    assert (position.side, position.qty, position.avg_cost) == (
        SIDE_SHORT,
        Decimal("5"),
        Decimal("110"),
    )


def test_reduce_only_never_flips_the_position_in_one_way_mode(
    swap_instrument: Instrument,
) -> None:
    """只减仓减不掉的部分不能被「反手开仓」消化：整笔拒绝，账本原样不动。"""

    book = PositionBook()
    book.apply(make_fill(inst_id=SWAP_INST_ID, qty="2", price="100"), swap_instrument)
    before = book.positions()

    with pytest.raises(PaperRejected):
        book.apply(
            make_fill(fill_id="fill2", inst_id=SWAP_INST_ID, side="sell", qty="3", price="110"),
            swap_instrument,
            reduce_only=True,
        )

    assert book.positions() == before


def test_position_book_rejects_swap_arguments_on_spot(spot_instrument: Instrument) -> None:
    """现货没有持仓方向也没有「只减仓」：把永续参数带进来必须报错，不静默忽略。"""

    book = PositionBook()

    with pytest.raises(ValidationError):
        book.apply(make_fill(), spot_instrument, pos_side=SIDE_LONG)
    with pytest.raises(ValidationError):
        book.apply(make_fill(), spot_instrument, reduce_only=True)


# ---------------------------------------------------------------- 类别分叉只有一处


def test_category_branch_appears_exactly_once_in_execution_package() -> None:
    """验收判据：`rg -c 'inst_type == "SPOT"' backend/app/execution` 结果为 1。

    在 pytest 里再锁一次，避免以后有人另写一处类别分支而这条命令没人跑。
    """

    branch = 'inst_type == "SPOT"'
    hits = [
        (path.relative_to(BACKEND_ROOT).as_posix(), line)
        for path in sorted(EXECUTION_DIR.rglob("*.py"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if branch in line
    ]

    assert len(hits) == 1, f"类别分叉必须只有一处, 实际:{hits}"

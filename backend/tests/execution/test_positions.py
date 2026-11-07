"""策略级虚拟持仓、收益归因与账户合计（全部纯函数）。"""

from decimal import Decimal

import pytest

from app.execution.core import positions as core

ZERO = Decimal("0")


def _long(quantity: str, price: str) -> core.PositionSnapshot:
    return core.apply_fill(
        core.empty("long"),
        side="buy",
        quantity=Decimal(quantity),
        price=Decimal(price),
    )


def test_long_open_add_and_partial_close() -> None:
    position = _long("2", "100")
    position = core.apply_fill(position, side="buy", quantity=Decimal("2"), price=Decimal("110"))
    assert position.quantity == Decimal("4")
    assert position.average_price == Decimal("105")

    position = core.apply_fill(
        position,
        side="sell",
        quantity=Decimal("1"),
        price=Decimal("115"),
        fee=Decimal("0.5"),
    )
    assert position.quantity == Decimal("3")
    assert position.average_price == Decimal("105")
    assert position.realized_pnl == Decimal("9.5")


def test_short_close_realizes_inverse_pnl() -> None:
    position = core.apply_fill(
        core.empty("short"),
        side="sell",
        quantity=Decimal("3"),
        price=Decimal("200"),
    )
    assert position.quantity == Decimal("3")
    position = core.apply_fill(position, side="buy", quantity=Decimal("1"), price=Decimal("190"))
    assert position.quantity == Decimal("2")
    assert position.realized_pnl == Decimal("10")


def test_full_close_zeroes_average() -> None:
    position = _long("1", "100")
    position = core.apply_fill(position, side="sell", quantity=Decimal("1"), price=Decimal("101"))
    assert position.quantity == ZERO
    assert position.average_price == ZERO
    assert position.realized_pnl == Decimal("1")


def test_over_close_is_rejected() -> None:
    with pytest.raises(core.PositionError):
        core.apply_fill(_long("1", "100"), side="sell", quantity=Decimal("2"), price=Decimal("100"))


def test_strategy_attribution_sums_to_combined_book() -> None:
    """各策略已实现盈亏之和 == 去掉策略维度的合并账本（可加性）。"""

    fills = [
        ("long", "buy", "2", "100"),
        ("long", "buy", "1", "110"),
        ("long", "sell", "1", "120"),
        ("short", "sell", "3", "200"),
        ("short", "buy", "1", "180"),
    ]

    per_strategy: dict[str, core.PositionSnapshot] = {}
    plan = {"s1": ("long", "short"), "s2": ("long", "short")}
    assignments = ["s1", "s1", "s1", "s2", "s2"]
    for (position_side, side, quantity, price), owner in zip(fills, assignments, strict=True):
        assert position_side in plan[owner]
        key = f"{owner}:{position_side}"
        current = per_strategy.get(key) or core.empty(position_side)
        per_strategy[key] = core.apply_fill(
            current, side=side, quantity=Decimal(quantity), price=Decimal(price)
        )

    combined: dict[str, core.PositionSnapshot] = {}
    for position_side, side, quantity, price in fills:
        current = combined.get(position_side) or core.empty(position_side)
        combined[position_side] = core.apply_fill(
            current, side=side, quantity=Decimal(quantity), price=Decimal(price)
        )

    per_strategy_pnl = sum((item.realized_pnl for item in per_strategy.values()), ZERO)
    combined_pnl = sum((item.realized_pnl for item in combined.values()), ZERO)
    assert abs(per_strategy_pnl - combined_pnl) <= Decimal("1e-9")


def test_mark_to_market_and_account_totals() -> None:
    rows = [
        core.PositionRow(1, 10, "BTC-USDT-SWAP", "long", Decimal("2"), Decimal("100"), ZERO),
        core.PositionRow(2, 10, "BTC-USDT-SWAP", "short", Decimal("1"), Decimal("120"), ZERO),
    ]
    marks = {(10, "long"): Decimal("110"), (10, "short"): Decimal("110")}
    valuations = core.mark_to_market(rows, marks)
    assert [item.unrealized_pnl for item in valuations] == [
        Decimal("20"),
        Decimal("10"),
    ]
    totals = core.account_totals(valuations)
    assert totals.unrealized_pnl == Decimal("30")
    assert totals.gross_notional == Decimal("330")
    assert totals.net_notional == Decimal("110")
    assert totals.positions == 2


def test_unrealized_ratio_sign() -> None:
    row = core.PositionRow(1, 10, "BTC-USDT-SWAP", "long", Decimal("1"), Decimal("100"), ZERO)
    valuation = core.mark_to_market([row], {(10, "long"): Decimal("90")})[0]
    assert core.unrealized_ratio(valuation) == Decimal("-0.1")

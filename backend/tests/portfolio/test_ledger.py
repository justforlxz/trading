"""FIFO 账本：验收给的三笔成交是已知答案，其余用例固定周边口径。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core import ValidationError
from app.portfolio import BUY, SELL, LedgerPosition, Lot, apply_fill, unrealized_pnl

D = Decimal


def replay(fills: list[tuple[str, str, str, str]]) -> LedgerPosition:
    """按 (side, qty, price, fee) 顺序重放；不碰数据库，纯函数。"""

    ledger = LedgerPosition(direction=None, lots=())
    for side, qty, price, fee in fills:
        ledger = apply_fill(ledger, side=side, qty=D(qty), price=D(price), fee=D(fee))
    return ledger


def test_fifo_realizes_twenty_and_keeps_the_second_lot_cost() -> None:
    """买入 1 张@100、1 张@110，卖出 1 张@120：已实现 20，剩余成本价 110。"""

    ledger = replay([(BUY, "1", "100", "0"), (BUY, "1", "110", "0"), (SELL, "1", "120", "0")])

    assert ledger.realized_pnl == D("20")
    assert ledger.direction == "long"
    assert ledger.qty == D("1")
    assert ledger.avg_cost == D("110")
    # 先买的那一批被卖掉，剩下第二批。
    assert ledger.lots == (Lot(D("1"), D("110")),)


def test_partial_close_keeps_the_earlier_lot_first() -> None:
    """卖半批：先冲掉最早的 0.4 张，剩余批次顺序不变。"""

    ledger = replay([(BUY, "1", "100", "0"), (BUY, "2", "200", "0"), (SELL, "0.4", "150", "0")])

    assert ledger.realized_pnl == D("20")
    assert ledger.qty == D("2.6")
    assert ledger.lots == (Lot(D("0.6"), D("100")), Lot(D("2"), D("200")))


def test_selling_more_than_held_flips_to_the_opposite_side() -> None:
    """卖超 1 张：先按 FIFO 平掉多头（已实现 +30），剩余 1 张按卖价开空。"""

    ledger = replay([(BUY, "1", "100", "0"), (BUY, "1", "110", "0"), (SELL, "3", "120", "0")])

    assert ledger.direction == "short"
    assert ledger.qty == D("1")
    assert ledger.avg_cost == D("120")
    assert ledger.realized_pnl == D("30")


def test_short_position_realizes_profit_when_price_falls() -> None:
    """空头：卖出 2 张@100，买回 2 张@90，已实现盈亏 20。"""

    ledger = replay([(SELL, "2", "100", "0"), (BUY, "2", "90", "0")])

    assert ledger.direction is None
    assert ledger.qty == D("0")
    assert ledger.realized_pnl == D("20")


def test_fee_is_deducted_from_realized_pnl_and_accumulated() -> None:
    """手续费全额计入已实现盈亏，并单独累计总额。"""

    ledger = replay([(BUY, "1", "100", "1.5"), (SELL, "1", "120", "1.5")])

    assert ledger.realized_pnl == D("17")
    assert ledger.fees == D("3")


def test_unrealized_pnl_uses_the_average_cost_of_remaining_lots() -> None:
    """未实现盈亏 =（标记价 − 剩余成本价）× 数量；空头方向相反。"""

    ledger = replay([(BUY, "2", "100", "0"), (BUY, "2", "110", "0")])
    assert unrealized_pnl(ledger, D("120")) == D("60")

    short = replay([(SELL, "2", "100", "0")])
    assert unrealized_pnl(short, D("90")) == D("20")


def test_contract_multiplier_scales_realized_and_unrealized_pnl() -> None:
    """合约面值 10：价差 10 的 1 张合约实现 100，剩余持仓浮盈同样乘 10。"""

    ledger = LedgerPosition(direction=None, lots=())
    ledger = apply_fill(ledger, side=BUY, qty=D("2"), price=D("100"), multiplier=D("10"))
    ledger = apply_fill(ledger, side=SELL, qty=D("1"), price=D("110"), multiplier=D("10"))

    assert ledger.realized_pnl == D("100")
    assert unrealized_pnl(ledger, D("120"), D("10")) == D("200")


@pytest.mark.parametrize(
    ("side", "qty", "price"),
    [("hold", "1", "100"), (BUY, "0", "100"), (BUY, "1", "0")],
)
def test_invalid_fills_are_rejected(side: str, qty: str, price: str) -> None:
    ledger = LedgerPosition(direction=None, lots=())
    with pytest.raises(ValidationError):
        apply_fill(ledger, side=side, qty=D(qty), price=D(price))

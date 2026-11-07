"""成本模型纯函数：资金费边界计数、滑点方向与费用口径（AC6）。"""

from datetime import UTC, datetime
from decimal import Decimal

from app.backtest.costs import (
    CostModel,
    count_funding_crossings,
    execution_prices,
    fee_cost,
    funding_cost,
    slippage_cost,
)


def moment(day: int = 1, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, minute, tzinfo=UTC)


def test_funding_boundary_counts_zero_one_and_two_crossings() -> None:
    assert count_funding_crossings(moment(hour=0), moment(hour=7)) == 0
    assert count_funding_crossings(moment(hour=0), moment(hour=8)) == 1
    assert count_funding_crossings(moment(hour=0), moment(hour=16)) == 2
    # 恰好在边界建仓，当次不计；恰好在边界平仓，当次计入。
    assert count_funding_crossings(moment(hour=8), moment(hour=8)) == 0
    assert count_funding_crossings(moment(hour=7), moment(hour=8)) == 1


def test_execution_prices_move_against_the_trader() -> None:
    entry, exit_ = execution_prices("long", Decimal("100"), Decimal("110"), Decimal("5"))
    assert entry == Decimal("100.05")
    assert exit_ == Decimal("109.945")

    entry, exit_ = execution_prices("short", Decimal("100"), Decimal("110"), Decimal("5"))
    assert entry == Decimal("99.95")
    assert exit_ == Decimal("110.055")


def test_fee_slippage_and_funding_amounts() -> None:
    assert fee_cost(Decimal("10"), Decimal("1000"), Decimal("1100")) == Decimal("2.1")
    assert slippage_cost(Decimal("5"), Decimal("1000"), Decimal("1100")) == Decimal("1.05")
    # 多头支付资金费，空头收取。
    assert funding_cost("long", Decimal("1"), Decimal("1000"), 2) == Decimal("0.2")
    assert funding_cost("short", Decimal("1"), Decimal("1000"), 2) == Decimal("-0.2")
    assert funding_cost("long", Decimal("1"), Decimal("1000"), 0) == Decimal("0")


def test_cost_model_selects_fee_role() -> None:
    model = CostModel(taker_fee_bps=Decimal("10"), maker_fee_bps=Decimal("2"))
    assert model.fee_bps() == Decimal("10")
    maker = CostModel(taker_fee_bps=Decimal("10"), maker_fee_bps=Decimal("2"), fee_role="maker")
    assert maker.fee_bps() == Decimal("2")


def test_cost_model_serializes_to_stable_text() -> None:
    model = CostModel(
        taker_fee_bps=Decimal("5"),
        maker_fee_bps=Decimal("2"),
        slippage_bps=Decimal("1"),
        funding_bps_per_period=Decimal("0.5"),
        fee_role="taker",
    )
    payload = model.as_dict()
    assert payload["taker_fee_bps"] == "5"
    assert payload["funding_bps_per_period"] == "0.5"
    assert payload["funding"] is True
    assert payload["fee_role"] == "taker"

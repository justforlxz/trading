"""成本模型纯函数（手算对照用例）。

v2 不再计资金费：成本只有手续费与滑点，`CostModel` 不再有 funding 入参/字段——
`as_dict()` 的逐字段断言就是这条约束的回归网。绩效指标与组合级口径的用例在
`tests/backtest/test_metrics.py`。
"""

from decimal import Decimal

import pytest

from app.backtest.costs import (
    CostModel,
    execution_prices,
    fee_cost,
    slippage_cost,
)

TOL = Decimal("1e-6")

# ------------------------------------------------------------------- 成本


def test_execution_prices_move_against_the_trader() -> None:
    entry, exit_ = execution_prices("long", Decimal("100"), Decimal("110"), Decimal("5"))
    assert entry == Decimal("100.05")
    assert exit_ == Decimal("109.945")

    entry, exit_ = execution_prices("short", Decimal("100"), Decimal("110"), Decimal("5"))
    assert entry == Decimal("99.95")
    assert exit_ == Decimal("110.055")


def test_unknown_side_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown side"):
        execution_prices("flat", Decimal("100"), Decimal("110"), Decimal("5"))


def test_fee_and_slippage_amounts() -> None:
    # 10 bps × (1000 + 1100) = 2.1；5 bps × 2100 = 1.05
    assert fee_cost(Decimal("10"), Decimal("1000"), Decimal("1100")) == Decimal("2.1")
    assert slippage_cost(Decimal("5"), Decimal("1000"), Decimal("1100")) == Decimal("1.05")
    # 名义金额取绝对值：空头负名义金额不改变成本口径。
    assert fee_cost(Decimal("10"), Decimal("-1000"), Decimal("1100")) == Decimal("2.1")


def test_cost_model_selects_fee_role() -> None:
    model = CostModel(taker_fee_bps=Decimal("10"), maker_fee_bps=Decimal("2"))
    assert model.fee_bps() == Decimal("10")
    maker = CostModel(taker_fee_bps=Decimal("10"), maker_fee_bps=Decimal("2"), fee_role="maker")
    assert maker.fee_bps() == Decimal("2")


def test_cost_model_serializes_without_funding_fields() -> None:
    model = CostModel(
        taker_fee_bps=Decimal("5"),
        maker_fee_bps=Decimal("2"),
        slippage_bps=Decimal("1"),
        fee_role="taker",
    )
    payload = model.as_dict()
    assert payload == {
        "taker_fee_bps": "5",
        "maker_fee_bps": "2",
        "slippage_bps": "1",
        "fee_role": "taker",
    }

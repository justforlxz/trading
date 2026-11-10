"""成本模型与回测指标纯函数（手算对照用例）。

v2 不再计资金费：成本只有手续费与滑点，`CostModel` 与 `compute_metrics`
都不再有 funding 入参/字段——本文件的键集合断言就是这条约束的回归网。
"""

from decimal import Decimal

import pytest

from app.backtest.costs import (
    CostModel,
    execution_prices,
    fee_cost,
    slippage_cost,
)
from app.backtest.metrics import (
    METRIC_NAMES,
    compute_metrics,
    default_annualization_factor,
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


# ------------------------------------------------------------------- 指标


def _metrics(**overrides: object) -> dict[str, Decimal]:
    payload: dict[str, object] = {
        "equity": [Decimal("100"), Decimal("110"), Decimal("100"), Decimal("110")],
        "initial_capital": Decimal("100"),
        "net_pnls": [Decimal("10"), Decimal("-11")],
        "traded_notional": Decimal("2000"),
        "total_fees": Decimal("5"),
        "total_slippage": Decimal("3"),
        "annualization_factor": Decimal("3"),
        "risk_free_rate": Decimal("0"),
    }
    payload.update(overrides)
    return compute_metrics(**payload)  # type: ignore[arg-type]


def test_ten_metrics_match_hand_computation() -> None:
    metrics = _metrics()
    assert set(metrics) == set(METRIC_NAMES)

    returns = [
        Decimal("0.1"),
        (Decimal("100") - Decimal("110")) / Decimal("110"),
        Decimal("0.1"),
    ]
    mean = sum(returns, Decimal(0)) / Decimal(3)
    std = (sum(((value - mean) ** 2 for value in returns), Decimal(0)) / Decimal(3)).sqrt()
    downside = (
        sum((min(value, Decimal(0)) ** 2 for value in returns), Decimal(0)) / Decimal(3)
    ).sqrt()
    annualizer = Decimal(3).sqrt()

    expected = {
        "total_return": Decimal("0.1"),
        # 3 个周期、年化因子 3 → (1.1)^(3/3) - 1 = 0.1
        "annualized_return": Decimal("0.1"),
        "max_drawdown": Decimal("10") / Decimal("110"),
        "sharpe": mean / std * annualizer,
        "sortino": mean / downside * annualizer,
        "win_rate": Decimal("0.5"),
        "profit_loss_ratio": Decimal("10") / Decimal("11"),
        "trade_count": Decimal("2"),
        "turnover": Decimal("20"),
        # 成本 = |手续费| + |滑点| = 5 + 3 = 8，占初始资金 8%。
        "cost_ratio": Decimal("0.08"),
    }
    for name, value in expected.items():
        assert abs(metrics[name] - value) < TOL, (name, metrics[name], value)


def test_metrics_reject_funding_argument() -> None:
    # v2 不计资金费：旧入参必须已经删掉，而不是被静默忽略。
    with pytest.raises(TypeError):
        compute_metrics(
            equity=[Decimal("100"), Decimal("110")],
            initial_capital=Decimal("100"),
            net_pnls=[Decimal("10")],
            traded_notional=Decimal("1000"),
            total_fees=Decimal("1"),
            total_slippage=Decimal("1"),
            total_funding=Decimal("1"),  # type: ignore[call-arg]
            annualization_factor=Decimal("3"),
            risk_free_rate=Decimal("0"),
        )


def test_annualization_factor_and_risk_free_rate_are_used() -> None:
    baseline = _metrics()
    faster = _metrics(annualization_factor=Decimal("252"))
    assert faster["annualized_return"] != baseline["annualized_return"]
    assert faster["sharpe"] != baseline["sharpe"]

    with_rate = _metrics(risk_free_rate=Decimal("0.03"))
    assert with_rate["sharpe"] < baseline["sharpe"]
    assert with_rate["sortino"] != baseline["sortino"]


def test_empty_trades_and_flat_curve_do_not_divide_by_zero() -> None:
    metrics = _metrics(equity=[Decimal("100"), Decimal("100")], net_pnls=[])
    assert metrics["total_return"] == Decimal("0")
    assert metrics["sharpe"] == Decimal("0")
    assert metrics["sortino"] == Decimal("0")
    assert metrics["win_rate"] == Decimal("0")
    assert metrics["profit_loss_ratio"] == Decimal("0")
    assert metrics["trade_count"] == Decimal("0")


def test_default_annualization_factor() -> None:
    assert default_annualization_factor("1d") == Decimal("252")
    assert default_annualization_factor("1h") == Decimal("8760")
    assert default_annualization_factor("4h") == Decimal("2190")

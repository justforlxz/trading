"""指标纯函数：10 个指标的手算对照与年化参数行为（AC8）。"""

from decimal import Decimal

from app.backtest.metrics import METRIC_NAMES, compute_metrics, default_annualization_factor

TOL = Decimal("1e-6")


def _metrics(**overrides):
    payload = {
        "equity": [Decimal("100"), Decimal("110"), Decimal("100"), Decimal("110")],
        "initial_capital": Decimal("100"),
        "net_pnls": [Decimal("10"), Decimal("-11")],
        "traded_notional": Decimal("2000"),
        "total_fees": Decimal("5"),
        "total_funding": Decimal("2"),
        "total_slippage": Decimal("3"),
        "annualization_factor": Decimal("3"),
        "risk_free_rate": Decimal("0"),
    }
    payload.update(overrides)
    return compute_metrics(**payload)


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
        "cost_ratio": Decimal("0.1"),
    }
    for name, value in expected.items():
        assert abs(metrics[name] - value) < TOL, (name, metrics[name], value)


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

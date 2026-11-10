"""回测指标（纯函数，固定点 Decimal）。

10 个指标名与回测报告一一对应。所有年化口径都由调用方传入
`annualization_factor` / `risk_free_rate`，公式里不写死 252 或 0，
改参数必然改变结果。

约定：

- `max_drawdown` 为正数幅度（0.1 表示从峰值回撤 10%）。
- `turnover` = 累计成交名义金额 / 初始资金（建仓与平仓两侧都计，买入持有约 2.0）。
- `cost_ratio` = (手续费 + 滑点) / 初始资金。
- 年化/夏普/索提诺在样本不足时返回 0（不伪造、不抛错）。
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.shared.timeframe import bar_seconds

MONEY_QUANT = Decimal("0.0000000001")
ONE = Decimal(1)
ZERO = Decimal(0)
DAYS_PER_YEAR = Decimal(365)
SECONDS_PER_DAY = Decimal(86400)

METRIC_NAMES: tuple[str, ...] = (
    "total_return",
    "annualized_return",
    "max_drawdown",
    "sharpe",
    "sortino",
    "win_rate",
    "profit_loss_ratio",
    "trade_count",
    "turnover",
    "cost_ratio",
)

METRIC_UNITS: dict[str, str] = {
    "total_return": "ratio",
    "annualized_return": "ratio",
    "max_drawdown": "ratio",
    "sharpe": "ratio",
    "sortino": "ratio",
    "win_rate": "ratio",
    "profit_loss_ratio": "ratio",
    "trade_count": "count",
    "turnover": "ratio",
    "cost_ratio": "ratio",
}


def quantize_money(value: Decimal) -> Decimal:
    """入库统一 10 位小数，保证同一计算重复落库逐位相同。"""

    return Decimal(value).quantize(MONEY_QUANT)


def default_annualization_factor(bar: str) -> Decimal:
    """默认年化因子：日线按 252 个交易日；日内按 365 天 24/7 连续市场。"""

    if bar == "1d":
        return Decimal(252)
    return DAYS_PER_YEAR * SECONDS_PER_DAY / Decimal(bar_seconds(bar))


def _div(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == ZERO:
        return ZERO
    return numerator / denominator


def _mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return ZERO
    return sum(values, ZERO) / Decimal(len(values))


def _std(values: Sequence[Decimal]) -> Decimal:
    """总体标准差（ddof=0），避免样本量小时出现无意义的除数。"""

    if not values:
        return ZERO
    mean = _mean(values)
    variance = sum(((value - mean) ** 2 for value in values), ZERO) / Decimal(len(values))
    return variance.sqrt()


def compute_metrics(
    *,
    equity: Sequence[Decimal],
    initial_capital: Decimal,
    net_pnls: Sequence[Decimal],
    traded_notional: Decimal,
    total_fees: Decimal,
    total_slippage: Decimal,
    annualization_factor: Decimal,
    risk_free_rate: Decimal,
) -> dict[str, Decimal]:
    """按权益曲线与成交汇总算 10 个指标；返回值已量化到 10 位小数。"""

    capital = Decimal(initial_capital)
    curve = [Decimal(value) for value in equity]
    final = curve[-1] if curve else capital
    total_return = _div(final - capital, capital)

    periods = len(curve) - 1
    annualized = ZERO
    if periods > 0:
        growth = ONE + total_return
        if growth <= ZERO:
            annualized = -ONE
        else:
            ratio = Decimal(annualization_factor) / Decimal(periods)
            annualized = (growth.ln() * ratio).exp() - ONE

    peak = capital
    max_drawdown = ZERO
    for value in curve:
        peak = max(peak, value)
        drawdown = _div(peak - value, peak) if peak > ZERO else ZERO
        max_drawdown = max(max_drawdown, drawdown)

    period_returns = [
        _div(curve[index] - curve[index - 1], curve[index - 1])
        for index in range(1, len(curve))
        if curve[index - 1] != ZERO
    ]
    period_rf = _div(Decimal(risk_free_rate), Decimal(annualization_factor))
    excess = [value - period_rf for value in period_returns]
    annualizer = Decimal(annualization_factor).sqrt()
    sharpe = _div(_mean(excess), _std(excess)) * annualizer
    downside = sum((min(value, ZERO) ** 2 for value in excess), ZERO)
    downside_deviation = (downside / Decimal(len(excess))).sqrt() if excess else ZERO
    sortino = _div(_mean(excess), downside_deviation) * annualizer

    pnls = [Decimal(value) for value in net_pnls]
    wins = [value for value in pnls if value > ZERO]
    losses = [value for value in pnls if value < ZERO]
    win_rate = _div(Decimal(len(wins)), Decimal(len(pnls)))
    average_win = _mean(wins)
    average_loss = _mean(losses)
    profit_loss_ratio = _div(average_win, abs(average_loss)) if losses else ZERO

    costs = abs(Decimal(total_fees)) + abs(Decimal(total_slippage))
    return {
        "total_return": quantize_money(total_return),
        "annualized_return": quantize_money(annualized),
        "max_drawdown": quantize_money(max_drawdown),
        "sharpe": quantize_money(sharpe),
        "sortino": quantize_money(sortino),
        "win_rate": quantize_money(win_rate),
        "profit_loss_ratio": quantize_money(profit_loss_ratio),
        "trade_count": quantize_money(Decimal(len(pnls))),
        "turnover": quantize_money(_div(Decimal(traded_notional), capital)),
        "cost_ratio": quantize_money(_div(costs, capital)),
    }


__all__ = [
    "METRIC_NAMES",
    "METRIC_UNITS",
    "compute_metrics",
    "default_annualization_factor",
    "quantize_money",
]

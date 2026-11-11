"""回测指标（纯函数，固定点 Decimal）。

三类计算都在本模块，都是纯函数、不碰 IO：

- `closed_trades`：把逐腿成交折成「一次开仓到一次平仓」的完整交易，带成本与盈亏；
- `compute_metrics`：按净值曲线与完整交易算 13 个标的级指标；
- `exposure_series` / `portfolio_metrics`：组合级口径——按 bar 的净敞口序列、每腿胜率、
  多腿与空腿各自的合计盈亏。

指标名与 `docs/prd/v2.md` §三.6「回测结果」的清单逐项对应；清单里的第 14 项「资金曲线」
是序列（由调用方逐 bar 落库），不是标量，所以不在这里的键集合里。

约定：

- `max_drawdown` 为正数幅度（0.1 表示从峰值回撤 10%）。
- `max_single_loss` 为负数（该笔亏了多少钱），没有亏损交易时为 0。
- `profit_loss_ratio`（盈亏比）= 平均盈利 / 平均亏损的绝对值；`profit_factor` = 盈利之和 /
  亏损之和的绝对值。两者口径不同，不能互相代替。
- `average_holding_hours` 取完整交易持仓时长的小时均值。
- 年化/夏普在样本不足时返回 0（不伪造、不抛错）。
- 一条腿的成交按**加权平均成本**配对，与引擎的持仓记账同一口径：平仓盈亏 =
  (平仓价 − 加权开仓价) × 数量 × 乘数 × 方向；开仓手续费与滑点按配对数量比例分摊到
  这笔交易上。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, getcontext, localcontext
from types import MappingProxyType

from app.backtest.simulation import LegFill, contract_multiplier, instrument_for
from app.core import InstrumentRef, InvariantViolation, ValidationError
from app.shared import bar_seconds
from app.strategy import TargetPortfolio

MONEY_QUANT = Decimal("0.0000000001")
ONE = Decimal(1)
ZERO = Decimal(0)
DAYS_PER_YEAR = Decimal(365)
SECONDS_PER_DAY = Decimal(86400)
SECONDS_PER_HOUR = Decimal(3600)
LONG = "long"
SHORT = "short"

METRIC_NAMES: tuple[str, ...] = (
    "initial_capital",
    "final_capital",
    "total_return",
    "annualized_return",
    "max_drawdown",
    "win_rate",
    "profit_loss_ratio",
    "profit_factor",
    "sharpe",
    "trade_count",
    "average_holding_hours",
    "max_single_win",
    "max_single_loss",
)

METRIC_UNITS: dict[str, str] = {
    "initial_capital": "quote",
    "final_capital": "quote",
    "total_return": "ratio",
    "annualized_return": "ratio",
    "max_drawdown": "ratio",
    "win_rate": "ratio",
    "profit_loss_ratio": "ratio",
    "profit_factor": "ratio",
    "sharpe": "ratio",
    "trade_count": "count",
    "average_holding_hours": "hours",
    "max_single_win": "quote",
    "max_single_loss": "quote",
}


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    """一次完整交易：某一腿从开仓到（部分或全部）平仓的配对结果。

    `entry_price` 是配对时的加权开仓均价（含滑点），`entry_time` 是该段持仓的建立时刻；
    `fee` 与 `slippage` 是开仓侧按数量分摊过来的那份加上平仓侧实付的那份，因此同一腿
    所有交易的 `fee` 之和等于该腿的成交手续费总额，不会被重复计入。
    `reason` 取平仓成交的原因（`rebalance` / `close` / `stop_loss` / `take_profit`）。
    """

    product_key: str
    inst_id: str
    inst_type: str
    side: str
    qty: Decimal
    entry_price: Decimal
    entry_time: datetime
    exit_price: Decimal
    exit_time: datetime
    fee: Decimal
    slippage: Decimal
    pnl: Decimal
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ExposurePoint:
    """一根 bar 收盘时在用的净敞口（多头权重之和减空头权重之和）。"""

    time: datetime
    net_exposure: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioMetrics:
    """组合级指标：单个标的的指标看不出多空两条腿各自的账，这四项补上。

    `leg_win_rate` 按 `product_key` 逐腿统计盈利笔数占比，不是组合整体胜率；
    `long_pnl` / `short_pnl` 分别是多头腿与空头腿全部完整交易的盈亏之和。
    """

    net_exposure: Decimal
    leg_win_rate: Mapping[str, Decimal]
    long_pnl: Decimal
    short_pnl: Decimal


def quantize_money(value: Decimal) -> Decimal:
    """入库统一 10 位小数，保证同一计算重复落库逐位相同。

    位数按被量化值自身的整数位放宽：短样本的年化收益可能大到几十位整数位，用默认
    28 位上下文量化会抛 `InvalidOperation`。这里只放宽上下文精度，不改变口径。
    """

    normalized = Decimal(value)
    needed = normalized.adjusted() + 2 + abs(MONEY_QUANT.as_tuple().exponent)
    with localcontext() as context:
        context.prec = max(getcontext().prec, needed)
        return normalized.quantize(MONEY_QUANT)


def default_annualization_factor(bar: str) -> Decimal:
    """默认年化因子：日线按 252 个交易日；日内按 365 天 24/7 连续市场。"""

    if bar == "1d":
        return Decimal(252)
    return DAYS_PER_YEAR * SECONDS_PER_DAY / Decimal(bar_seconds(bar))


def closed_trades(
    fills: Sequence[LegFill],
    instruments: Mapping[str, InstrumentRef],
) -> tuple[ClosedTrade, ...]:
    """把成交序列折成完整交易；每笔平仓成交产生一条记录。

    `instruments` 是产品键到标的静态信息的映射：数量乘数由 `contract_multiplier` 按
    类别规则表取值，本函数不判断类别；`inst_type` 原样带到交易记录上，事后按腿回放时
    不必再猜这个标的当初是现货还是永续。

    加仓时开仓均价按数量加权、开仓时刻保持首次建仓的时刻，与引擎的持仓记账一致；
    一笔平仓成交只配对到「平仓那一刻的持仓」，部分平仓因此各成一条交易。方向反转由
    撮合层拆成「先平后开」两条成交，这里不做跨零配对。
    """

    open_lots: dict[str, _OpenLot] = {}
    multipliers: dict[str, Decimal] = {}
    trades: list[ClosedTrade] = []
    for fill in fills:
        instrument = instrument_for(instruments, fill.product_key)
        multiplier = multipliers.get(fill.product_key)
        if multiplier is None:
            multiplier = contract_multiplier(instrument)
            multipliers[fill.product_key] = multiplier
        if fill.opening:
            current = open_lots.get(fill.product_key)
            open_lots[fill.product_key] = _open(current, fill)
            continue

        current = open_lots.get(fill.product_key)
        if current is None or current.side != fill.side:
            raise InvariantViolation(
                f"{fill.product_key} 的平仓成交找不到同方向的持仓, side={fill.side}"
            )
        if fill.qty > current.qty:
            raise InvariantViolation(
                f"{fill.product_key} 的平仓数量 {fill.qty} 超过持仓 {current.qty}"
            )

        share = _div(fill.qty, current.qty)
        fee = fill.fee + current.fee * share
        slippage = fill.slippage + current.slippage * share
        trades.append(
            ClosedTrade(
                product_key=fill.product_key,
                inst_id=fill.inst_id,
                inst_type=instrument.inst_type,
                side=fill.side,
                qty=fill.qty,
                entry_price=current.entry_price,
                entry_time=current.entry_time,
                exit_price=fill.price,
                exit_time=fill.bar_open_time,
                fee=fee,
                slippage=slippage,
                pnl=current.pnl(fill.price, fill.qty, multiplier),
                reason=fill.reason,
            )
        )

        remaining = current.qty - fill.qty
        if remaining == ZERO:
            del open_lots[fill.product_key]
        else:
            open_lots[fill.product_key] = current.remaining(remaining, share)
    return tuple(trades)


def exposure_series(
    targets: Sequence[TargetPortfolio],
    bar_times: Sequence[datetime],
) -> tuple[ExposurePoint, ...]:
    """按 bar 记录净敞口序列，口径与引擎的生效时刻一致。

    `TargetPortfolio.as_of` 是所依据的 K 线开盘时刻，只在**下一根** K 线上生效，因此
    第 i 根 bar 收盘时在用的是 `as_of` 等于第 i−1 根 bar 的那份目标组合；没有新目标
    时持仓不动，敞口沿用上一次生效的值。第 1 根 bar 之前没有任何目标，敞口为 0。

    `as_of` 不在时间轴上的目标组合直接判错：它永远不会生效，静默跳过会把「这条腿本该
    有敞口」记成 0，读记录的人无法从数字里看出被丢掉了。
    """

    known = set(bar_times)
    due: dict[datetime, TargetPortfolio] = {}
    for target in targets:
        if target.as_of in due:
            raise ValidationError(f"同一时刻 {target.as_of.isoformat()} 给了两份目标组合")
        if target.as_of not in known:
            raise ValidationError(f"目标组合的时刻 {target.as_of.isoformat()} 不在行情时间轴上")
        due[target.as_of] = target

    points: list[ExposurePoint] = []
    current = ZERO
    previous: datetime | None = None
    for moment in bar_times:
        if previous is not None and previous in due:
            current = due[previous].net_exposure
        points.append(ExposurePoint(time=moment, net_exposure=quantize_money(current)))
        previous = moment
    return tuple(points)


def portfolio_metrics(
    trades: Sequence[ClosedTrade],
    exposure: Sequence[ExposurePoint],
) -> PortfolioMetrics:
    """算组合级四项：净敞口、每腿胜率、多腿合计盈亏、空腿合计盈亏。"""

    wins: dict[str, int] = {}
    counts: dict[str, int] = {}
    long_pnl = ZERO
    short_pnl = ZERO
    for trade in trades:
        counts[trade.product_key] = counts.get(trade.product_key, 0) + 1
        if trade.pnl > ZERO:
            wins[trade.product_key] = wins.get(trade.product_key, 0) + 1
        if trade.side == LONG:
            long_pnl += trade.pnl
        else:
            short_pnl += trade.pnl

    leg_win_rate = {
        key: quantize_money(_div(Decimal(wins.get(key, 0)), Decimal(counts[key])))
        for key in sorted(counts)
    }
    return PortfolioMetrics(
        net_exposure=exposure[-1].net_exposure if exposure else ZERO,
        leg_win_rate=MappingProxyType(leg_win_rate),
        long_pnl=quantize_money(long_pnl),
        short_pnl=quantize_money(short_pnl),
    )


def compute_metrics(
    *,
    equity: Sequence[Decimal],
    initial_capital: Decimal,
    trades: Sequence[ClosedTrade],
    annualization_factor: Decimal,
    risk_free_rate: Decimal,
) -> dict[str, Decimal]:
    """按权益曲线与完整交易算 13 个指标；返回值已量化到 10 位小数。"""

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

    pnls = [Decimal(trade.pnl) for trade in trades]
    wins = [value for value in pnls if value > ZERO]
    losses = [value for value in pnls if value < ZERO]
    win_rate = _div(Decimal(len(wins)), Decimal(len(pnls)))
    profit_loss_ratio = _div(_mean(wins), abs(_mean(losses))) if losses else ZERO
    profit_factor = _div(sum(wins, ZERO), abs(sum(losses, ZERO))) if losses else ZERO

    holdings = [Decimal((trade.exit_time - trade.entry_time).total_seconds()) for trade in trades]
    average_holding_hours = _div(_mean(holdings), SECONDS_PER_HOUR)

    return {
        "initial_capital": quantize_money(capital),
        "final_capital": quantize_money(final),
        "total_return": quantize_money(total_return),
        "annualized_return": quantize_money(annualized),
        "max_drawdown": quantize_money(max_drawdown),
        "win_rate": quantize_money(win_rate),
        "profit_loss_ratio": quantize_money(profit_loss_ratio),
        "profit_factor": quantize_money(profit_factor),
        "sharpe": quantize_money(sharpe),
        "trade_count": quantize_money(Decimal(len(pnls))),
        "average_holding_hours": quantize_money(average_holding_hours),
        "max_single_win": quantize_money(max(wins, default=ZERO)),
        "max_single_loss": quantize_money(min(losses, default=ZERO)),
    }


@dataclass(frozen=True, slots=True)
class _OpenLot:
    """一条腿当前未平仓的那部分：加权开仓均价、建立时刻、已付成本与方向。"""

    side: str
    qty: Decimal
    entry_price: Decimal
    entry_time: datetime
    fee: Decimal
    slippage: Decimal

    def pnl(self, exit_price: Decimal, qty: Decimal, multiplier: Decimal) -> Decimal:
        sign = ONE if self.side == LONG else -ONE
        return sign * (Decimal(exit_price) - self.entry_price) * qty * multiplier

    def remaining(self, qty: Decimal, share: Decimal) -> _OpenLot:
        return _OpenLot(
            side=self.side,
            qty=qty,
            entry_price=self.entry_price,
            entry_time=self.entry_time,
            fee=self.fee * (ONE - share),
            slippage=self.slippage * (ONE - share),
        )


def _open(current: _OpenLot | None, fill: LegFill) -> _OpenLot:
    """开仓成交并入持仓；已有同方向持仓时按数量加权开仓价，建立时刻保持首次。"""

    if current is None:
        return _OpenLot(
            side=fill.side,
            qty=fill.qty,
            entry_price=fill.price,
            entry_time=fill.bar_open_time,
            fee=fill.fee,
            slippage=fill.slippage,
        )
    if current.side != fill.side:
        raise InvariantViolation(
            f"{fill.product_key} 的反向持仓必须由两条成交拆开, 不能在建仓成交里跨过"
        )
    total = current.qty + fill.qty
    blended = (current.entry_price * current.qty + fill.price * fill.qty) / total
    return _OpenLot(
        side=current.side,
        qty=total,
        entry_price=blended,
        entry_time=current.entry_time,
        fee=current.fee + fill.fee,
        slippage=current.slippage + fill.slippage,
    )


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


__all__ = [
    "METRIC_NAMES",
    "METRIC_UNITS",
    "ClosedTrade",
    "ExposurePoint",
    "PortfolioMetrics",
    "closed_trades",
    "compute_metrics",
    "default_annualization_factor",
    "exposure_series",
    "portfolio_metrics",
    "quantize_money",
]

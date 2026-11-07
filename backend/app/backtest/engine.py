"""回测引擎（纯函数）：策略腿 + 已确认 K 线 → 成交流水与权益曲线。

执行口径（P1 固定，不做参数优化或滚动再训练）：

- 窗口内首根可成交 bar 的 `close` 建仓，持有到窗口内最后一根 bar 的 `close`
  平仓，`exit_reason="window_end"`；不做盘中撮合、不做调仓（买 & 持有）。
- 每个时点的估值只用 `open_time <= ts` 的 bar（`BarSeries.last_at`），
  决策不读取未来数据；缺口沿用上一根已知收盘价，绝不用其它周期插值。
- 所有金额在 Decimal 上计算，落库前量化到 10 位小数。
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.backtest import costs as cost_rules
from app.backtest.costs import CostModel
from app.backtest.errors import BacktestError
from app.backtest.metrics import quantize_money

ONE = Decimal(1)
ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class Bar:
    ts: datetime
    close: Decimal


@dataclass(frozen=True, slots=True)
class BarSeries:
    """单标的已确认 bar 序列（升序、已裁剪到回测窗口）。"""

    instrument_id: int
    bars: tuple[Bar, ...]

    def upto(self, moment: datetime) -> tuple[Bar, ...]:
        """只暴露 `ts <= moment` 的 bar，作为唯一的取数入口。"""

        return tuple(bar for bar in self.bars if bar.ts <= moment)

    def last_at(self, moment: datetime) -> Bar | None:
        visible = self.upto(moment)
        return visible[-1] if visible else None


@dataclass(frozen=True, slots=True)
class LegSpec:
    instrument_id: int
    inst_id: str
    side: str
    target_weight: Decimal
    rank: int = 0


@dataclass(frozen=True, slots=True)
class Trade:
    instrument_id: int
    inst_id: str
    side: str
    entry_ts: datetime
    exit_ts: datetime
    entry_px: Decimal
    exit_px: Decimal
    qty: Decimal
    gross_pnl: Decimal
    fees: Decimal
    funding: Decimal
    slippage: Decimal
    net_pnl: Decimal
    bars_held: int
    exit_reason: str = "window_end"


@dataclass(frozen=True, slots=True)
class EquityPoint:
    ts: datetime
    equity: Decimal
    cash: Decimal
    exposure: Decimal
    drawdown: Decimal


@dataclass(frozen=True, slots=True)
class Simulation:
    trades: tuple[Trade, ...]
    equity: tuple[EquityPoint, ...]
    traded_notional: Decimal
    total_fees: Decimal
    total_funding: Decimal
    total_slippage: Decimal
    net_pnls: tuple[Decimal, ...] = field(default_factory=tuple)


def _apply_slippage(side: str, close_in: Decimal, close_out: Decimal, bps: Decimal):
    return cost_rules.execution_prices(side, close_in, close_out, bps)


def simulate(
    *,
    legs: Sequence[LegSpec],
    series: Mapping[int, BarSeries],
    initial_capital: Decimal,
    cost_model: CostModel,
    window_start: datetime,
    window_end: datetime,
) -> Simulation:
    """按窗口内已确认 bar 跑一次买 & 持有回测。"""

    capital = Decimal(initial_capital)
    if capital <= ZERO:
        raise BacktestError("backtest_invalid_capital", "initial_capital must be positive")
    if window_end <= window_start:
        raise BacktestError("backtest_invalid_window", "window end must be after start")
    if not legs:
        raise BacktestError("strategy_no_legs", "strategy has no legs to backtest")

    prepared: list[_Prepared] = [
        _prepare(
            leg,
            _trim(series.get(leg.instrument_id), window_start, window_end),
            capital,
            cost_model,
        )
        for leg in sorted(legs, key=lambda leg: (leg.rank, leg.instrument_id))
    ]

    timeline = sorted({bar.ts for item in prepared for bar in item.bars.bars})
    if not timeline:
        raise BacktestError(
            "insufficient_data",
            "no confirmed candles inside the window",
            details={"window": {"start": window_start.isoformat(), "end": window_end.isoformat()}},
        )

    points: list[EquityPoint] = []
    peak = capital
    for moment in timeline:
        cash = capital
        position_value = ZERO
        exposure = ZERO
        fees = ZERO
        funding = ZERO
        for item in prepared:
            if moment < item.entry_ts:
                continue
            cash -= item.sign * item.qty * item.entry_px
            fees += item.entry_fee
            if moment >= item.exit_ts:
                cash += item.sign * item.qty * item.exit_px
                fees += item.exit_fee
                funding += item.funding
            else:
                bar = item.bars.last_at(moment)
                if bar is None:  # pragma: no cover - moment >= entry_ts 必有 bar
                    continue
                position_value += item.sign * item.qty * bar.close
                exposure += abs(item.qty * bar.close)
                funding += item.funding_until(moment)
        equity = cash + position_value - fees - funding
        peak = max(peak, equity)
        drawdown = ZERO if peak <= ZERO else equity / peak - ONE
        points.append(
            EquityPoint(
                ts=moment,
                equity=quantize_money(equity),
                cash=quantize_money(cash),
                exposure=quantize_money(exposure),
                drawdown=quantize_money(drawdown),
            )
        )

    trades = tuple(item.trade() for item in prepared)
    return Simulation(
        trades=trades,
        equity=tuple(points),
        traded_notional=sum((item.traded_notional for item in prepared), ZERO),
        total_fees=sum((trade.fees for trade in trades), ZERO),
        total_funding=sum((trade.funding for trade in trades), ZERO),
        total_slippage=sum((trade.slippage for trade in trades), ZERO),
        net_pnls=tuple(trade.net_pnl for trade in trades),
    )


@dataclass(frozen=True, slots=True)
class _Prepared:
    leg: LegSpec
    bars: BarSeries
    sign: Decimal
    entry_ts: datetime
    exit_ts: datetime
    entry_px: Decimal
    exit_px: Decimal
    qty: Decimal
    entry_fee: Decimal
    exit_fee: Decimal
    funding: Decimal
    funding_bps: Decimal
    slippage: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    traded_notional: Decimal

    def funding_until(self, moment: datetime) -> Decimal:
        crossings = cost_rules.count_funding_crossings(self.entry_ts, min(moment, self.exit_ts))
        return cost_rules.funding_cost(self.leg.side, self.funding_bps, self._notional, crossings)

    @property
    def _notional(self) -> Decimal:
        return self.qty * self.entry_px

    def trade(self) -> Trade:
        return Trade(
            instrument_id=self.leg.instrument_id,
            inst_id=self.leg.inst_id,
            side=self.leg.side,
            entry_ts=self.entry_ts,
            exit_ts=self.exit_ts,
            entry_px=quantize_money(self.entry_px),
            exit_px=quantize_money(self.exit_px),
            qty=quantize_money(self.qty),
            gross_pnl=quantize_money(self.gross_pnl),
            fees=quantize_money(self.entry_fee + self.exit_fee),
            funding=quantize_money(self.funding),
            slippage=quantize_money(self.slippage),
            net_pnl=quantize_money(self.net_pnl),
            bars_held=sum(1 for bar in self.bars.bars if self.entry_ts <= bar.ts <= self.exit_ts),
            exit_reason="window_end",
        )


def _trim(series: BarSeries | None, start: datetime, end: datetime) -> BarSeries | None:
    """窗口边界在引擎内再剪一次：窗口之外的 bar 永不参与计算。"""

    if series is None:
        return None
    bars = tuple(bar for bar in series.bars if start <= bar.ts < end)
    if not bars:
        return None
    return BarSeries(instrument_id=series.instrument_id, bars=bars)


def _prepare(
    leg: LegSpec,
    series: BarSeries | None,
    capital: Decimal,
    cost_model: CostModel,
) -> _Prepared:
    if series is None or not series.bars:
        raise BacktestError(
            "insufficient_data",
            f"no confirmed candles for {leg.inst_id}",
            details={"gaps": [{"instrument_id": leg.instrument_id, "inst_id": leg.inst_id}]},
        )
    if leg.side not in ("long", "short"):
        raise BacktestError("strategy_invalid_side", f"unknown side: {leg.side!r}")

    entry = series.bars[0]
    exit_bar = series.bars[-1]
    if entry.close <= ZERO or exit_bar.close <= ZERO:
        raise BacktestError(
            "backtest_invalid_price",
            f"non-positive close price for {leg.inst_id}",
            details={"instrument_id": leg.instrument_id},
        )
    entry_px, exit_px = _apply_slippage(
        leg.side, entry.close, exit_bar.close, cost_model.slippage_bps
    )
    notional = capital * abs(leg.target_weight)
    qty = quantize_money(notional / entry_px)
    if qty <= ZERO:
        raise BacktestError(
            "backtest_invalid_notional",
            f"target weight too small for {leg.inst_id}",
            details={"instrument_id": leg.instrument_id},
        )

    sign = ONE if leg.side == "long" else -ONE
    entry_notional = qty * entry_px
    exit_notional = qty * exit_px
    fee_bps = cost_model.fee_bps()
    entry_fee = cost_rules.fee_cost(fee_bps, entry_notional, ZERO)
    exit_fee = cost_rules.fee_cost(fee_bps, ZERO, exit_notional)
    slippage = cost_rules.slippage_cost(cost_model.slippage_bps, entry_notional, exit_notional)
    crossings = cost_rules.count_funding_crossings(entry.ts, exit_bar.ts)
    funding = (
        cost_rules.funding_cost(
            leg.side, cost_model.funding_bps_per_period, entry_notional, crossings
        )
        if cost_model.funding_enabled
        else ZERO
    )
    gross_pnl = sign * qty * (exit_px - entry_px)
    net_pnl = gross_pnl - entry_fee - exit_fee - funding

    return _Prepared(
        leg=leg,
        bars=series,
        sign=sign,
        entry_ts=entry.ts,
        exit_ts=exit_bar.ts,
        entry_px=entry_px,
        exit_px=exit_px,
        qty=qty,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        funding=funding,
        funding_bps=cost_model.funding_bps_per_period,
        slippage=slippage,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        traded_notional=entry_notional + exit_notional,
    )


@dataclass(frozen=True, slots=True)
class Window:
    """一个评估窗口；`role` 用于 walk-forward 切分校验（train / test / eval）。"""

    name: str
    start: datetime
    end: datetime
    role: str = "eval"


def validate_windows(windows: Sequence[Window]) -> None:
    """窗口必须非空、不重叠、按时间升序；训练段严格早于测试段。"""

    if not windows:
        raise BacktestError("backtest_window_empty", "at least one window is required")
    names: set[str] = set()
    for window in windows:
        if not window.name:
            raise BacktestError("backtest_window_invalid", "window name must not be empty")
        if window.name in names:
            raise BacktestError(
                "backtest_window_invalid",
                f"duplicate window name: {window.name!r}",
                details={"name": window.name},
            )
        names.add(window.name)
        if window.end <= window.start:
            raise BacktestError(
                "backtest_window_invalid",
                f"window {window.name!r} end must be after start",
                details={"name": window.name},
            )

    ordered = sorted(windows, key=lambda window: window.start)
    for previous, current in itertools.pairwise(ordered):
        if current.start < previous.end:
            raise BacktestError(
                "backtest_window_overlap",
                f"windows {previous.name!r} and {current.name!r} overlap",
                details={"previous": previous.name, "current": current.name},
            )

    train = [window for window in windows if window.role == "train"]
    test = [window for window in windows if window.role == "test"]
    if train and test:
        latest_train_end = max(window.end for window in train)
        earliest_test_start = min(window.start for window in test)
        if latest_train_end > earliest_test_start:
            raise BacktestError(
                "backtest_walk_forward_order",
                "train windows must end before test windows start",
                details={
                    "train_end": latest_train_end.isoformat(),
                    "test_start": earliest_test_start.isoformat(),
                },
            )


__all__ = [
    "Bar",
    "BarSeries",
    "EquityPoint",
    "LegSpec",
    "Simulation",
    "Trade",
    "Window",
    "simulate",
    "validate_windows",
]

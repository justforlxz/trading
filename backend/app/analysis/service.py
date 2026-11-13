"""标的详情分析编排。

数据口径：

- quote 的 `last` 取所选来源最新一根日线收盘价；没有日线时退回当前周期最后一根。
  数据库没有标记价与指数价来源，因此 `mark` / `index` 恒为 `None`，不拿最新价顶替。
- K 线只读取标的自身 OKX 行情。优先 `okx_spot` / `okx_swap`，存量数据使用 `okx`
  时继续可读；不会把美股代理行情拼进同一条序列。
- 趋势、动量、波动、成交量与相对强弱全部调用 `app.indicators` 的注册指标计算；
  关键价位、收益率对齐与读数模板在本模块完成。
- 相关系数按收益率序列对齐后取最近 60 个有效样本，再调用 `app.market` 的 Pearson
  纯函数。样本不足时系数为 `None`，样本数照实返回。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from math import isfinite

from app.backtest import BacktestRunHeader, list_instrument_runs
from app.core import Bar, ValidationError
from app.indicators import Series, compute
from app.instrument import Instrument, list_instruments, okx_source
from app.market import (
    CRYPTO,
    CandleGap,
    IntegrityReport,
    aligned_pairs,
    candle_sources,
    integrity,
    load_candles,
    pearson,
)
from app.shared import bar_seconds
from app.strategy import list_instances
from app.watchlist import group_of, tracked_instruments

__all__ = ["ANALYSIS_BARS", "Analysis", "AnalysisCandles", "instrument_analysis"]

ANALYSIS_BARS: tuple[str, ...] = ("1d", "4h", "1h")
CHART_LIMIT = 240
CORRELATION_WINDOW = 60
LEVEL_WINDOW = 20
RELATIVE_STRENGTH_WINDOW = 20
SLOPE_WINDOW = 5
VOLUME_WINDOW = 20
ATR_AVERAGE_WINDOW = 20
MIN_ANALYSIS_BARS = CORRELATION_WINDOW + 1
LINKED_STRATEGY_WINDOW_DAYS = 30
LINKED_STRATEGY_LIMIT = 10

_ZERO = Decimal(0)
_ONE = Decimal(1)
_HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class PricePoint:
    price: Decimal
    as_of: datetime
    source: str
    change: Decimal | None = None
    change_pct: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Quote:
    last: PricePoint | None
    mark: PricePoint | None
    index: PricePoint | None


@dataclass(frozen=True, slots=True)
class OverlayPoint:
    time: datetime
    value: Decimal


@dataclass(frozen=True, slots=True)
class Overlay:
    name: str
    points: tuple[OverlayPoint, ...]


@dataclass(frozen=True, slots=True)
class AnalysisCandles:
    data_source: str
    available_from: datetime | None
    available_to: datetime | None
    gaps: tuple[CandleGap, ...]
    candles: tuple[Bar, ...]
    overlays: tuple[Overlay, ...]


@dataclass(frozen=True, slots=True)
class TrendIndicators:
    close: Decimal | None
    ma20: Decimal | None
    ma60: Decimal | None
    price_vs_ma20_pct: Decimal | None
    price_vs_ma60_pct: Decimal | None
    ma20_slope_pct: Decimal | None
    ma60_slope_pct: Decimal | None
    slope_window: int


@dataclass(frozen=True, slots=True)
class MomentumIndicators:
    rsi14: Decimal | None
    macd: Decimal | None
    macd_signal: Decimal | None
    macd_hist: Decimal | None


@dataclass(frozen=True, slots=True)
class VolatilityIndicators:
    atr14: Decimal | None
    atr_pct: Decimal | None
    atr_pct_avg20: Decimal | None


@dataclass(frozen=True, slots=True)
class VolumeIndicators:
    current: Decimal | None
    average20: Decimal | None
    relative: Decimal | None


@dataclass(frozen=True, slots=True)
class RelativeStrengthIndicators:
    benchmark_inst_id: str | None
    window: int
    symbol_return_pct: Decimal | None
    benchmark_return_pct: Decimal | None
    excess_return_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class Indicators:
    trend: TrendIndicators
    momentum: MomentumIndicators
    volatility: VolatilityIndicators
    volume: VolumeIndicators
    relative_strength: RelativeStrengthIndicators
    readings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Levels:
    window: int
    high20: Decimal | None
    low20: Decimal | None
    high_distance_pct: Decimal | None
    low_distance_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class Correlation:
    inst_id: str
    product_key: str
    role: str
    coefficient: Decimal | None
    sample_size: int
    window: int
    window_start: datetime | None
    window_end: datetime | None


@dataclass(frozen=True, slots=True)
class LinkedStrategy:
    run_id: str
    strategy_instance_id: str
    strategy_name: str
    strategy_id: str
    data_source: str
    total_return_pct: Decimal
    max_drawdown_pct: Decimal
    trade_count: int
    backtest_start_date: date
    backtest_end_date: date
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Coverage:
    bar: str
    data_source: str
    available: bool
    unavailable_reason: str | None
    available_from: datetime | None
    available_to: datetime | None
    candle_count: int
    gap_count: int
    last_synced_at: datetime | None


@dataclass(frozen=True, slots=True)
class Analysis:
    instrument: Instrument
    bar: str
    quote: Quote
    candles: AnalysisCandles
    indicators: Indicators
    levels: Levels
    correlations: tuple[Correlation, ...]
    linked_strategies: tuple[LinkedStrategy, ...]
    coverage: tuple[Coverage, ...]


def instrument_analysis(inst_id: str, bar: str) -> Analysis | None:
    """组装一个标的的完整分析；标的未登记返回 `None`。"""

    if bar not in ANALYSIS_BARS:
        raise ValidationError(f"分析周期只支持 {', '.join(ANALYSIS_BARS)}，实际 {bar!r}")
    symbol = inst_id.strip()
    instrument = next((row for row in list_instruments() if row.symbol == symbol), None)
    if instrument is None:
        return None

    source = _source_for(instrument, bar)
    bars = _bars_for(instrument, bar, source)
    report = integrity(symbol, bar, source=source)
    candles = _candles(bars, source, report)
    benchmark = _benchmark_for(instrument)
    correlations = _correlations(instrument, benchmark, bar)
    relative_strength = _relative_strength(bars, benchmark, bar)
    indicators = _indicators(bars, relative_strength)
    levels = _levels(bars)
    quote = _quote(instrument, bar, bars, source)
    report_readings = _readings(indicators, levels, correlations, report)
    indicators = Indicators(
        trend=indicators.trend,
        momentum=indicators.momentum,
        volatility=indicators.volatility,
        volume=indicators.volume,
        relative_strength=indicators.relative_strength,
        readings=report_readings,
    )
    return Analysis(
        instrument=instrument,
        bar=bar,
        quote=quote,
        candles=candles,
        indicators=indicators,
        levels=levels,
        correlations=correlations,
        linked_strategies=_linked_strategies(instrument),
        coverage=_coverage(instrument),
    )


def _source_for(instrument: Instrument, bar: str) -> str:
    preferred = okx_source(instrument.inst_type)
    available = candle_sources([instrument.symbol], bar).get(instrument.symbol, set())
    if preferred in available:
        return preferred
    if "okx" in available:
        return "okx"
    return preferred


def _bars_for(instrument: Instrument, bar: str, source: str) -> tuple[Bar, ...]:
    return tuple(
        candle for candle in load_candles(instrument.symbol, bar, source=source) if candle.confirm
    )


def _candles(bars: tuple[Bar, ...], source: str, report: IntegrityReport) -> AnalysisCandles:
    selected = bars[-CHART_LIMIT:]
    times = {candle.open_time for candle in selected}
    return AnalysisCandles(
        data_source=source,
        available_from=report.start,
        available_to=report.end,
        gaps=report.gaps,
        candles=selected,
        overlays=(
            _overlay("MA20", bars, 20, times),
            _overlay("MA60", bars, 60, times),
        ),
    )


def _overlay(name: str, bars: tuple[Bar, ...], period: int, times: set[datetime]) -> Overlay:
    series = compute("sma", bars, {"period": period})
    return Overlay(
        name=name,
        points=tuple(
            OverlayPoint(time=point.time, value=value)
            for point in series.points
            if point.time in times
            for value in (point.values.get("sma"),)
            if value is not None
        ),
    )


def _quote(instrument: Instrument, bar: str, bars: tuple[Bar, ...], source: str) -> Quote:
    daily_source = _source_for(instrument, "1d")
    daily = _bars_for(instrument, "1d", daily_source)
    selected = daily if daily else bars
    selected_source = daily_source if daily else source
    if not selected:
        return Quote(last=None, mark=None, index=None)
    latest = selected[-1]
    previous = selected[-2] if len(selected) >= 2 else None
    change = None if previous is None else latest.close - previous.close
    change_pct = (
        None
        if previous is None or previous.close == _ZERO
        else (latest.close - previous.close) / previous.close * _HUNDRED
    )
    step = timedelta(seconds=bar_seconds("1d" if daily else bar))
    return Quote(
        last=PricePoint(
            price=latest.close,
            as_of=latest.open_time + step,
            source=selected_source,
            change=change,
            change_pct=change_pct,
        ),
        mark=None,
        index=None,
    )


def _indicators(bars: tuple[Bar, ...], relative_strength: RelativeStrengthIndicators) -> Indicators:
    close = bars[-1].close if bars else None

    ma20_series = compute("sma", bars, {"period": 20})
    ma60_series = compute("sma", bars, {"period": 60})
    ma20 = _last_value(ma20_series, "sma")
    ma60 = _last_value(ma60_series, "sma")
    trend = TrendIndicators(
        close=close,
        ma20=ma20,
        ma60=ma60,
        price_vs_ma20_pct=_distance_pct(close, ma20),
        price_vs_ma60_pct=_distance_pct(close, ma60),
        ma20_slope_pct=_slope_pct(ma20_series, "sma", SLOPE_WINDOW),
        ma60_slope_pct=_slope_pct(ma60_series, "sma", SLOPE_WINDOW),
        slope_window=SLOPE_WINDOW,
    )

    rsi_series = compute("rsi", bars, {"period": 14})
    macd_series = compute("macd", bars, {"fast": 12, "slow": 26, "signal": 9})
    momentum = MomentumIndicators(
        rsi14=_last_value(rsi_series, "rsi"),
        macd=_last_value(macd_series, "macd"),
        macd_signal=_last_value(macd_series, "signal"),
        macd_hist=_last_value(macd_series, "hist"),
    )

    atr_series = compute("atr", bars, {"period": 14})
    atr = _last_value(atr_series, "atr")
    atr_pct = atr / close * _HUNDRED if atr is not None and close not in (None, _ZERO) else None
    closes = {bar.open_time: bar.close for bar in bars}
    atr_history = [
        (point.values["atr"], closes[point.time])
        for point in atr_series.points
        if point.values.get("atr") is not None and point.time in closes
    ][-ATR_AVERAGE_WINDOW:]
    atr_pcts = [
        value / price * _HUNDRED
        for value, price in atr_history
        if value is not None and price != _ZERO
    ]
    volatility = VolatilityIndicators(
        atr14=atr,
        atr_pct=atr_pct,
        atr_pct_avg20=sum(atr_pcts, _ZERO) / Decimal(len(atr_pcts)) if atr_pcts else None,
    )

    recent_volumes = [bar.volume for bar in bars[-VOLUME_WINDOW:]]
    average20 = (
        sum(recent_volumes, _ZERO) / Decimal(len(recent_volumes)) if recent_volumes else None
    )
    current_volume = bars[-1].volume if bars else None
    volume = VolumeIndicators(
        current=current_volume,
        average20=average20,
        relative=(
            current_volume / average20
            if current_volume is not None and average20 not in (None, _ZERO)
            else None
        ),
    )
    return Indicators(
        trend=trend,
        momentum=momentum,
        volatility=volatility,
        volume=volume,
        relative_strength=relative_strength,
        readings=(),
    )


def _levels(bars: tuple[Bar, ...]) -> Levels:
    window = bars[-LEVEL_WINDOW:]
    if not window:
        return Levels(
            window=LEVEL_WINDOW,
            high20=None,
            low20=None,
            high_distance_pct=None,
            low_distance_pct=None,
        )
    close = window[-1].close
    high = max(bar.high for bar in window)
    low = min(bar.low for bar in window)
    return Levels(
        window=LEVEL_WINDOW,
        high20=high,
        low20=low,
        high_distance_pct=_distance_pct(high, close),
        low_distance_pct=_distance_pct(low, close),
    )


def _relative_strength(
    bars: tuple[Bar, ...], benchmark: Instrument | None, bar: str
) -> RelativeStrengthIndicators:
    empty = RelativeStrengthIndicators(
        benchmark_inst_id=None if benchmark is None else benchmark.symbol,
        window=RELATIVE_STRENGTH_WINDOW,
        symbol_return_pct=None,
        benchmark_return_pct=None,
        excess_return_pct=None,
    )
    if benchmark is None:
        return empty
    benchmark_bars = _bars_for(benchmark, bar, _source_for(benchmark, bar))
    left = {candle.open_time: candle.close for candle in bars}
    right = {candle.open_time: candle.close for candle in benchmark_bars}
    common = sorted(left.keys() & right.keys())[-(RELATIVE_STRENGTH_WINDOW + 1) :]
    if len(common) < RELATIVE_STRENGTH_WINDOW + 1:
        return empty
    start, end = common[0], common[-1]
    symbol_return = _return_pct(left[start], left[end])
    benchmark_return = _return_pct(right[start], right[end])
    excess = (
        None
        if symbol_return is None or benchmark_return is None
        else symbol_return - benchmark_return
    )
    return RelativeStrengthIndicators(
        benchmark_inst_id=benchmark.symbol,
        window=RELATIVE_STRENGTH_WINDOW,
        symbol_return_pct=symbol_return,
        benchmark_return_pct=benchmark_return,
        excess_return_pct=excess,
    )


def _benchmark_for(instrument: Instrument) -> Instrument | None:
    keys = ("BTC",) if instrument.asset_type == CRYPTO else ("QQQ", "SPY")
    instruments = list_instruments()
    for key in keys:
        matches = [
            row
            for row in instruments
            if row.product_key == key and row.product_key != instrument.product_key
        ]
        same_type = [row for row in matches if row.inst_type == instrument.inst_type]
        pool = same_type or matches
        same_quote = [row for row in pool if row.quote_currency == instrument.quote_currency]
        if same_quote:
            return same_quote[0]
        if pool:
            return pool[0]
    return None


def _correlations(
    instrument: Instrument, benchmark: Instrument | None, bar: str
) -> tuple[Correlation, ...]:
    candidates: list[tuple[Instrument, str]] = []
    if benchmark is not None and benchmark.symbol != instrument.symbol:
        candidates.append((benchmark, "benchmark"))
    group = group_of(instrument.symbol)
    if group is not None:
        for row in tracked_instruments(group):
            if row.symbol == instrument.symbol or row.product_key == instrument.product_key:
                continue
            if any(row.symbol == candidate.symbol for candidate, _ in candidates):
                continue
            candidates.append((row, "related"))
            if len(candidates) >= 3:
                break

    own_bars = _bars_for(instrument, bar, _source_for(instrument, bar))
    own_returns = _return_series(own_bars)
    results: list[Correlation] = []
    for candidate, role in candidates:
        candidate_bars = _bars_for(candidate, bar, _source_for(candidate, bar))
        candidate_returns = _return_series(candidate_bars)
        aligned = aligned_pairs(own_returns, candidate_returns)[-CORRELATION_WINDOW:]
        coefficient = (
            None
            if not aligned
            else pearson([row[1] for row in aligned], [row[2] for row in aligned])
        )
        results.append(
            Correlation(
                inst_id=candidate.symbol,
                product_key=candidate.product_key,
                role=role,
                coefficient=None if coefficient is None else Decimal(str(coefficient)),
                sample_size=len(aligned),
                window=CORRELATION_WINDOW,
                window_start=aligned[0][0] if aligned else None,
                window_end=aligned[-1][0] if aligned else None,
            )
        )
    return tuple(results)


def _return_series(bars: tuple[Bar, ...]) -> list[tuple[datetime, float]]:
    points: list[tuple[datetime, float]] = []
    for previous, current in pairwise(bars):
        if previous.close == _ZERO:
            continue
        value = float((current.close - previous.close) / previous.close)
        if isfinite(value):
            points.append((current.open_time, value))
    return points


def _linked_strategies(instrument: Instrument) -> tuple[LinkedStrategy, ...]:
    since = datetime.now(UTC) - timedelta(days=LINKED_STRATEGY_WINDOW_DAYS)
    headers = list_instrument_runs(
        instrument.symbol, created_since=since, limit=LINKED_STRATEGY_LIMIT
    )
    instances, _ = list_instances(limit=500)
    names = {instance.instance_id: instance.name for instance in instances}
    return tuple(_linked(header, names) for header in headers)


def _linked(header: BacktestRunHeader, names: dict[str, str]) -> LinkedStrategy:
    return LinkedStrategy(
        run_id=header.run_id,
        strategy_instance_id=header.strategy_instance_id,
        strategy_name=names.get(header.strategy_instance_id, header.strategy_id),
        strategy_id=header.strategy_id,
        data_source=header.data_source,
        total_return_pct=header.metrics["total_return"] * _HUNDRED,
        max_drawdown_pct=header.metrics["max_drawdown"] * _HUNDRED,
        trade_count=int(header.metrics["trade_count"]),
        backtest_start_date=header.start_date,
        backtest_end_date=header.end_date,
        created_at=header.created_at,
    )


def _coverage(instrument: Instrument) -> tuple[Coverage, ...]:
    rows: list[Coverage] = []
    for bar in ANALYSIS_BARS:
        source = _source_for(instrument, bar)
        report = integrity(instrument.symbol, bar, source=source)
        if report.present == 0:
            available = False
            reason = "尚未同步"
        elif report.present < MIN_ANALYSIS_BARS:
            available = False
            reason = f"仅有 {report.present} 根 K 线，不足 {MIN_ANALYSIS_BARS} 根"
        else:
            available = True
            reason = None
        rows.append(
            Coverage(
                bar=bar,
                data_source=source,
                available=available,
                unavailable_reason=reason,
                available_from=report.start,
                available_to=report.end,
                candle_count=report.present,
                gap_count=len(report.gaps),
                last_synced_at=report.last_synced_at,
            )
        )
    return tuple(rows)


def _readings(
    indicators: Indicators,
    levels: Levels,
    correlations: tuple[Correlation, ...],
    report: IntegrityReport,
) -> tuple[str, ...]:
    trend = indicators.trend
    sentences: list[str] = []
    if trend.close is not None and trend.ma20 is not None and trend.price_vs_ma20_pct is not None:
        side = "上方" if trend.price_vs_ma20_pct >= _ZERO else "下方"
        slope = _plain(trend.ma20_slope_pct, 2, suffix="%")
        sentences.append(
            f"收盘价 {_plain(trend.close, 4)}，MA20 为 {_plain(trend.ma20, 4)}，"
            f"价格位于 MA20 {side} {_plain(abs(trend.price_vs_ma20_pct), 2, suffix='%')}；"
            f"MA20 的 {trend.slope_window} 根斜率是 {slope}。"
        )
    if indicators.momentum.rsi14 is not None and indicators.momentum.macd is not None:
        sentences.append(
            f"RSI(14) 为 {_plain(indicators.momentum.rsi14, 2)}，MACD 为 "
            f"{_plain(indicators.momentum.macd, 4)}，信号线为 "
            f"{_plain(indicators.momentum.macd_signal, 4)}，柱状值为 "
            f"{_plain(indicators.momentum.macd_hist, 4)}。"
        )
    if indicators.volatility.atr14 is not None and indicators.volatility.atr_pct is not None:
        sentences.append(
            f"ATR(14) 为 {_plain(indicators.volatility.atr14, 4)}，占收盘价 "
            f"{_plain(indicators.volatility.atr_pct, 2, suffix='%')}。"
        )
    if indicators.volume.relative is not None:
        relative = indicators.volume.relative
        benchmark = indicators.relative_strength.benchmark_inst_id
        excess = indicators.relative_strength.excess_return_pct
        extra = (
            f"，近 {indicators.relative_strength.window} 根相对 {benchmark} 的超额收益为 "
            f"{_plain(excess, 2, suffix=' 个百分点')}"
            if benchmark is not None and excess is not None
            else ""
        )
        sentences.append(f"当前成交量是 {VOLUME_WINDOW} 根均量的 {_plain(relative, 2)} 倍{extra}。")
    if not sentences:
        return ("该周期尚未同步，无法生成指标解释。",)
    if len(sentences) < 2:
        sentences.append("其余指标因有效样本不足，暂未生成解释。")
    if len(sentences) < 3 and levels.high20 is not None and report.start is not None:
        sentences.append(
            f"近 {LEVEL_WINDOW} 根高点为 {_plain(levels.high20, 4)}，低点为 "
            f"{_plain(levels.low20, 4)}；相关系数有效样本最多为 {report.present - 1} 个。"
        )
    return tuple(sentences[:3])


def _last_value(series: Series, key: str) -> Decimal | None:
    for point in reversed(series.points):
        value = point.values.get(key)
        if value is not None:
            return value
    return None


def _slope_pct(series: Series, key: str, window: int) -> Decimal | None:
    known = [point.values.get(key) for point in series.points if point.values.get(key) is not None]
    if len(known) <= window:
        return None
    current = known[-1]
    previous = known[-1 - window]
    if current is None or previous in (None, _ZERO):
        return None
    return (current - previous) / previous * _HUNDRED


def _distance_pct(value: Decimal | None, reference: Decimal | None) -> Decimal | None:
    if value is None or reference in (None, _ZERO):
        return None
    return (value - reference) / reference * _HUNDRED


def _return_pct(start: Decimal, end: Decimal) -> Decimal | None:
    if start == _ZERO:
        return None
    return (end - start) / start * _HUNDRED


def _plain(value: Decimal | None, places: int, *, suffix: str = "") -> str:
    if value is None:
        return "数据不足"
    quantum = Decimal(1).scaleb(-places)
    return f"{value.quantize(quantum)}{suffix}"

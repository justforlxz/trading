"""市场域对外编排：可用区间、完整性报告、两标的相关性与当前有效行情。

读侧只读库，不做任何补齐或插值：缺多少根就报多少根，可用区间就是库里真实的首末。
相关性在这里完成「按 open_time 对齐两条序列」的编排，系数仍由纯函数计算。
「当前有效行情」在这里完成「查标的 → 判时段 → 选来源 → 取最新一根」的编排，
时段与来源的选择本身仍是 `app.market.session` 的纯函数。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core import Bar, ValidationError
from app.db import session_scope
from app.instrument import Instrument, resolve_instrument
from app.market.candles import duplicate_open_times, expected_open_times, find_gaps
from app.market.correlation import METHODS, correlate, p_value
from app.market.model import Candle
from app.market.session import UNKNOWN_ASSET, asset_session, day_asset_type, primary_source
from app.market.sync import data_range, load_candles, normalize_bar_or_raise
from app.shared import bar_seconds


@dataclass(frozen=True, slots=True)
class CandleGap:
    """一段连续缺失的窗口 `[start, end)` 与其中的缺失根数。"""

    start: datetime
    end: datetime
    missing: int


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    """库内某标的某一周期的完整性：真实首末、应有/实有根数、缺口与重复。"""

    symbol: str
    bar: str
    start: datetime | None
    end: datetime | None
    expected: int
    present: int
    missing: int
    gaps: tuple[CandleGap, ...]
    duplicates: tuple[datetime, ...]


@dataclass(frozen=True, slots=True)
class PairCorrelation:
    """两个标的按 open_time 对齐后的相关系数与显著性。"""

    symbol_a: str
    symbol_b: str
    bar: str
    method: str
    sample_size: int
    coefficient: float | None
    p_value: float | None


def integrity(symbol: str, bar: str, *, source: str | None = None) -> IntegrityReport:
    """检测库内缺口与重复；只读，不会写入任何补齐数据。

    统计区间取库里真实的首末 K 线（`[first, last + 一个周期)`），
    因此「可用区间」与缺口报告是同一份事实。日线的期望序列按**该序列所属市场**的
    交易日排（代理行情按美股时段、OKX 行情按 UTC+8 零点），来源不同不能共用一个网格。
    """

    canonical = normalize_bar_or_raise(bar)
    first_last = data_range(symbol, canonical, source=source)
    if first_last is None:
        return IntegrityReport(
            symbol=symbol,
            bar=canonical,
            start=None,
            end=None,
            expected=0,
            present=0,
            missing=0,
            gaps=(),
            duplicates=(),
        )

    first, last = first_last
    step = timedelta(seconds=bar_seconds(canonical))
    window_end = last + step
    actual = [
        candle.open_time
        for candle in load_candles(symbol, canonical, start=first, end=window_end, source=source)
    ]
    boundary = _day_boundary(symbol, canonical, source)
    gaps = find_gaps(actual, first, window_end, canonical, boundary)
    duplicates = duplicate_open_times(actual)
    present = len(set(actual))
    expected_times = expected_open_times(first, window_end, canonical, boundary)
    return IntegrityReport(
        symbol=symbol,
        bar=canonical,
        start=first,
        end=last,
        expected=len(expected_times),
        present=present,
        missing=len(expected_times) - present,
        gaps=tuple(
            CandleGap(
                start=gap_start,
                end=gap_end,
                # 日线的期望网格不是均匀的（周末与休市日没有日线），只能数网格里的时刻。
                missing=sum(1 for moment in expected_times if gap_start <= moment < gap_end),
            )
            for gap_start, gap_end in gaps
        ),
        duplicates=tuple(duplicates),
    )


def _day_boundary(symbol: str, bar: str, source: str | None) -> str:
    """这条序列按哪个市场的交易日排：代理行情按标的资产，OKX 行情按 UTC+8。

    日线网格只在处理日线时才需要，非日线周期传资产类别只是为了让签名统一。
    来源为空时取库里这一标的实际落过的来源：只有一种来源就按它的市场排；多种来源
    混存无法用一个网格同时对齐，退回标的自身的资产时段。
    """

    asset_type = _asset_type(symbol)
    if bar != "1d":
        return asset_type
    return day_asset_type(asset_type, source if source is not None else _single_source(symbol, bar))


def _asset_type(symbol: str) -> str:
    """标的所属资产；表里没有这条标的时按未登记分类处理（临时取值同 `session`）。"""

    with session_scope() as session:
        asset_type = session.scalars(
            select(Instrument.asset_type).where(Instrument.symbol == symbol)
        ).first()
    return UNKNOWN_ASSET if asset_type is None else asset_type


def _single_source(symbol: str, bar: str) -> str | None:
    """库内该标的该周期落过的唯一来源；多于一种来源时返回 `None`。"""

    with session_scope() as session:
        sources = set(
            session.scalars(select(Candle.source).where(Candle.symbol == symbol, Candle.bar == bar))
        )
    return sources.pop() if len(sources) == 1 else None


def correlation(
    symbol_a: str,
    symbol_b: str,
    bar: str,
    *,
    method: str = "pearson",
    start: datetime | None = None,
    end: datetime | None = None,
    source: str | None = None,
) -> PairCorrelation:
    """两个标的同一周期的收盘价相关性：先按 open_time 取交集，再算系数。

    样本不足时系数为 `None`（不硬凑、不插值），样本数照实返回。
    """

    canonical = normalize_bar_or_raise(bar)
    if method not in METHODS:
        raise ValidationError(f"不支持的相关性方法 {method!r}; 支持: {', '.join(METHODS)}")
    if symbol_a == symbol_b:
        raise ValidationError("相关性需要两个不同的标的")

    left = {
        candle.open_time: float(candle.close)
        for candle in load_candles(symbol_a, canonical, start=start, end=end, source=source)
    }
    right = {
        candle.open_time: float(candle.close)
        for candle in load_candles(symbol_b, canonical, start=start, end=end, source=source)
    }
    common = sorted(left.keys() & right.keys())
    coefficient = correlate(
        [left[open_time] for open_time in common],
        [right[open_time] for open_time in common],
        method=method,
    )
    return PairCorrelation(
        symbol_a=symbol_a,
        symbol_b=symbol_b,
        bar=canonical,
        method=method,
        sample_size=len(common),
        coefficient=coefficient,
        p_value=None if coefficient is None else p_value(coefficient, len(common)),
    )


def current_bar(
    product_key: str,
    bar: str,
    *,
    inst_type: str,
    at: datetime | None = None,
) -> Bar | None:
    """按产品键取「当前有效行情」：一根带来源与资产时段的 K 线。

    来源不是常量，而是「资产时段 × 资产类别」的查表结果：代币化股票在美股交易时段
    读代理行情，休市时段读 OKX 合约行情；加密资产始终读 OKX 行情。所选来源在库里
    没有 K 线时返回 `None`——不用另一个来源的价格顶替，也不外推。

    `market_session` 描述的是这根 K 线自身的时段（按它的 `open_time` 判定），不是
    调用时刻的时段：一根凌晨取到的日线仍然属于它开盘时的那个时段。

    标的解析一律走 `app.instrument.resolve_instrument`：同一产品挂了多个报价时由它
    按「与永续同报价优先、其次 USDT」挑，本模块不再自己按 `symbol` 排序挑一行——
    两份规则迟早分叉，而 USDC 计价的现货被当成 USDT 那条会带出假价差。
    """

    canonical = normalize_bar_or_raise(bar)
    moment = datetime.now(tz=UTC) if at is None else at
    if moment.tzinfo is None:
        raise ValidationError("当前行情的判定时刻必须带时区")

    instrument = resolve_instrument(product_key, inst_type)
    session_state = asset_session(instrument.asset_type, moment, inst_type=instrument.inst_type)
    source = primary_source(session_state, instrument.asset_type, instrument.inst_type)

    statement = (
        select(Candle)
        .where(
            Candle.symbol == instrument.symbol,
            Candle.bar == canonical,
            Candle.source == source,
        )
        .order_by(Candle.open_time.desc())
        .limit(1)
    )
    with session_scope() as session:
        row = session.scalars(statement).first()
        loaded = None if row is None else row.to_bar()
    if loaded is None:
        return None
    return replace(
        loaded,
        market_session=asset_session(
            instrument.asset_type, loaded.open_time, inst_type=instrument.inst_type
        ),
    )

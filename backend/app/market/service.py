"""市场域对外编排：可用区间、完整性报告与两标的相关性。

读侧只读库，不做任何补齐或插值：缺多少根就报多少根，可用区间就是库里真实的首末。
相关性在这里完成「按 open_time 对齐两条序列」的编排，系数仍由纯函数计算。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core import ValidationError
from app.market.candles import duplicate_open_times, expected_open_times, find_gaps
from app.market.correlation import METHODS, correlate, p_value
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
    因此「可用区间」与缺口报告是同一份事实。
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
    gaps = find_gaps(actual, first, window_end, canonical)
    duplicates = duplicate_open_times(actual)
    present = len(set(actual))
    expected = len(expected_open_times(first, window_end, canonical))
    return IntegrityReport(
        symbol=symbol,
        bar=canonical,
        start=first,
        end=last,
        expected=expected,
        present=present,
        missing=expected - present,
        gaps=tuple(
            CandleGap(
                start=gap_start,
                end=gap_end,
                missing=int((gap_end - gap_start).total_seconds() // step.total_seconds()),
            )
            for gap_start, gap_end in gaps
        ),
        duplicates=tuple(duplicates),
    )


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

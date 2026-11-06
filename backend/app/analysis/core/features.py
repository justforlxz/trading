"""全市场特征截面（P1-11）：收益率、波动率、ATR、量比 z 与区间高低点。

只依赖标准库：运行时镜像不装 numpy，而这些计算都是 O(n) 的小序列运算。
所有函数都是纯函数：输入已按时间升序对齐的 K 线，输出 `float | None`；
**未定义一律返回 `None`**，绝不用 0 或 NaN 冒充（与 S4 的 `defined` 口径一致）。

口径（写进 `docs` 与 `market_snapshot.extras`，便于回溯）：

- `ret_Nd` = `close[-1] / close[-1-N] - 1`，简单收益率；
- `vol_20d` = 最近 20 根日线对数收益率的样本标准差（不年化）；
- `atr_14` = 最近 14 根真实波幅的**简单均值**（价格单位，不做 Wilder 平滑）；
- `volume_z` = 最新成交量相对最近 20 根均值的 z 分数（样本标准差）；
- `high_20d` / `low_20d` = 最近 20 根的最高价 / 最低价。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from math import isfinite, log, sqrt

MIN_BARS = 2
DEFAULT_VOL_WINDOW = 20
DEFAULT_ATR_WINDOW = 14
DEFAULT_RANGE_WINDOW = 20


@dataclass(frozen=True, slots=True)
class Bar:
    """计算特征所需的最小 K 线视图（只取已确认的日线）。"""

    open_time: datetime
    high: float
    low: float
    close: float
    vol: float


@dataclass(frozen=True, slots=True)
class CrossSection:
    """单只标的在某个截面时刻的特征；`None` 表示该口径不可用。"""

    ret_1d: float | None
    ret_5d: float | None
    ret_20d: float | None
    vol_20d: float | None
    atr_14: float | None
    volume_z: float | None
    high_20d: float | None
    low_20d: float | None
    bars: int

    @property
    def defined(self) -> bool:
        """是否有可用于聚类的收益特征（至少 1 日收益可用）。"""

        return self.ret_1d is not None


def _floats(values: Sequence[float]) -> list[float] | None:
    result = [float(value) for value in values]
    if not all(isfinite(value) for value in result):
        return None
    return result


def total_return(closes: Sequence[float], periods: int) -> float | None:
    """最近 `periods` 根 K 线的累计收益率；样本不足或价格非正时未定义。"""

    values = _floats(closes)
    if values is None or periods < 1 or len(values) < periods + 1:
        return None
    start = values[-1 - periods]
    end = values[-1]
    if start <= 0.0 or end <= 0.0:
        return None
    return end / start - 1.0


def log_returns(closes: Sequence[float]) -> list[float] | None:
    """相邻收盘价的对数收益率序列；含非正/非有限价格时整体未定义。"""

    values = _floats(closes)
    if values is None or len(values) < 2 or any(value <= 0.0 for value in values):
        return None
    return [log(end / start) for start, end in pairwise(values)]


def sample_std(values: Sequence[float]) -> float | None:
    """样本标准差（ddof=1）；样本不足或零方差时未定义。"""

    numbers = _floats(values)
    if numbers is None or len(numbers) < 2:
        return None
    mean = sum(numbers) / len(numbers)
    variance = sum((value - mean) ** 2 for value in numbers) / (len(numbers) - 1)
    if variance <= 0.0:
        return None
    return sqrt(variance)


def volatility(closes: Sequence[float], window: int = DEFAULT_VOL_WINDOW) -> float | None:
    """最近 `window` 根日线对数收益率的样本标准差（不年化）。"""

    returns = log_returns(closes)
    if returns is None or window < 2 or len(returns) < window:
        return None
    return sample_std(returns[-window:])


def true_ranges(bars: Sequence[Bar]) -> list[float]:
    """真实波幅序列；第一根没有前收，按 `high - low` 计。"""

    ranges: list[float] = []
    previous_close: float | None = None
    for bar in bars:
        if previous_close is None:
            ranges.append(bar.high - bar.low)
        else:
            ranges.append(
                max(
                    bar.high - bar.low,
                    abs(bar.high - previous_close),
                    abs(bar.low - previous_close),
                )
            )
        previous_close = bar.close
    return ranges


def average_true_range(bars: Sequence[Bar], window: int = DEFAULT_ATR_WINDOW) -> float | None:
    """最近 `window` 根真实波幅的简单均值（价格单位）。"""

    if window < 1 or len(bars) < window:
        return None
    ranges = true_ranges(bars)[-window:]
    return sum(ranges) / len(ranges)


def volume_z(volumes: Sequence[float], window: int = DEFAULT_VOL_WINDOW) -> float | None:
    """最新成交量相对最近 `window` 根均值的 z 分数；零方差时未定义。"""

    values = _floats(volumes)
    if values is None or window < 2 or len(values) < window:
        return None
    sample = values[-window:]
    deviation = sample_std(sample)
    if deviation is None:
        return None
    mean = sum(sample) / len(sample)
    return (sample[-1] - mean) / deviation


def cross_section(bars: Sequence[Bar]) -> CrossSection:
    """把一段日线压成一条截面特征；调用方保证 `bars` 按时间升序。"""

    if not bars:
        return CrossSection(None, None, None, None, None, None, None, None, 0)
    closes = [bar.close for bar in bars]
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]
    volumes = [bar.vol for bar in bars]
    window_start = max(0, len(bars) - DEFAULT_RANGE_WINDOW)
    return CrossSection(
        ret_1d=total_return(closes, 1),
        ret_5d=total_return(closes, 5),
        ret_20d=total_return(closes, 20),
        vol_20d=volatility(closes),
        atr_14=average_true_range(bars),
        volume_z=volume_z(volumes),
        high_20d=max(highs[window_start:]),
        low_20d=min(lows[window_start:]),
        bars=len(bars),
    )


__all__ = [
    "DEFAULT_ATR_WINDOW",
    "DEFAULT_RANGE_WINDOW",
    "DEFAULT_VOL_WINDOW",
    "MIN_BARS",
    "Bar",
    "CrossSection",
    "average_true_range",
    "cross_section",
    "log_returns",
    "sample_std",
    "total_return",
    "true_ranges",
    "volatility",
    "volume_z",
]

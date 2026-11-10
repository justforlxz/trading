"""滚动相关性与两标的相对强弱：一对序列在每个时间点上的运算，没有 IO。

与 `app.market.correlation` 的分工：那边是「一段序列 → 一个系数」，这边是
「一对序列 → 每个时间点一个系数」。窗口内样本不足、常数序列、非有限值一律记
`None`，不插值，也不拿不满的窗口凑一个数。

术语沿用 `app.market.correlation`：「未定义」用 `None` 表示，绝不返回 NaN。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from math import isfinite

from app.core import ValidationError
from app.market.correlation import pearson

# 一个观测点：该根 K 线的 `open_time`（带时区、精确到秒）+ 参与计算的数值。
Point = tuple[datetime, float]


def index_series(series: Sequence[Point], *, label: str = "序列") -> dict[datetime, float]:
    """序列 → 时间戳索引；同一时间戳出现多次时后一个覆盖前一个。

    相关计算里「一个时刻一个值」只有这一条规则：滚动窗口、矩阵的交叉格与对角线
    都走它，样本数不会因为某格走了另一条路径而对不上。
    """

    points: dict[datetime, float] = {}
    for moment, value in series:
        if moment.tzinfo is None:
            raise ValidationError(f"{label} 的时间戳必须带时区:{moment.isoformat()}")
        points[moment] = float(value)
    return points


def aligned_pairs(
    series_a: Sequence[Point], series_b: Sequence[Point]
) -> list[tuple[datetime, float, float]]:
    """按时间戳取交集，按时间升序返回 `(时刻, a 值, b 值)`。

    只保留两条序列都有的时间点：不插值、不外推、不拿相邻时刻顶替。同一时间戳在
    一条序列里出现多次时后一个覆盖前一个——行情来源的选择是调用方的事，这里只
    保证「一个时刻一个值」。
    """

    left = index_series(series_a, label="序列 A")
    right = index_series(series_b, label="序列 B")
    common = sorted(left.keys() & right.keys())
    return [(moment, left[moment], right[moment]) for moment in common]


def _window_size(window: int) -> int:
    if window < 1:
        raise ValidationError(f"滚动窗口必须是正整数:{window}")
    return window


def rolling_correlation(
    series_a: Sequence[Point],
    series_b: Sequence[Point],
    window: int,
) -> list[tuple[datetime, float | None]]:
    """滚动 Pearson 相关：每个时间点给出「含该点在内的最近 `window` 个交集样本」的系数。

    输出与交集序列等长，且时间戳逐个对应：前 `window - 1` 个时刻窗口未满，系数为
    `None`（不插值，也不用部分窗口凑数）。窗口内数值含非有限值或某一侧方差为 0 时
    同样是 `None`，由 `app.market.correlation` 的同一套判定给出。
    """

    size = _window_size(window)
    pairs = aligned_pairs(series_a, series_b)
    coefficients: list[tuple[datetime, float | None]] = []
    for index, (moment, _, _) in enumerate(pairs):
        if index + 1 < size:
            coefficients.append((moment, None))
            continue
        block = pairs[index + 1 - size : index + 1]
        coefficients.append((moment, pearson([row[1] for row in block], [row[2] for row in block])))
    return coefficients


def relative_strength_ratio(
    series_a: Sequence[Point],
    series_b: Sequence[Point],
) -> list[tuple[datetime, float | None]]:
    """两标的相对强弱：交集时间点上逐个相除 `a / b`。

    分母为 0（或结果不是有限值）时记 `None`，不折成一个很大的数。这是**跨标的**
    的比值，与单标的的 RSI（`app.indicators` 里的「相对强弱指标」）不是同一件事，
    因此不进指标注册表——注册表只承载单标的时序指标。
    """

    ratios: list[tuple[datetime, float | None]] = []
    for moment, value_a, value_b in aligned_pairs(series_a, series_b):
        if value_b == 0.0:
            ratios.append((moment, None))
            continue
        ratio = value_a / value_b
        ratios.append((moment, ratio if isfinite(ratio) else None))
    return ratios

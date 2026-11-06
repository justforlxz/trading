"""市场共振与相关性突变（P1-12）。

共振定义为「同一截面里朝同一方向运动的成员占比」，因此强度对同向比例单调：
注入 30% / 60% / 90% 的同向涨幅，强度必然依次不减。这一性质正是验收口径。

相关性突变针对「原本弱相关、最近突然高度同向」的情形：把时间轴切成基线段与
最近窗口段，分别算相关系数；只有**最近窗口足够强**且**与基线差距足够大**才标记。

纯函数：输入数值序列，输出判定结果；未定义用 `None` / `defined=False` 表达。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

from app.analysis.core.correlation import MIN_SAMPLES, pearson

FLAT_EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class Breadth:
    """截面广度：上涨 / 下跌 / 走平家数与占比。"""

    up: int
    down: int
    flat: int
    total: int

    @property
    def defined(self) -> bool:
        return self.total > 0

    @property
    def up_ratio(self) -> float | None:
        return None if self.total == 0 else self.up / self.total

    @property
    def down_ratio(self) -> float | None:
        return None if self.total == 0 else self.down / self.total


def breadth(returns: Sequence[float], *, epsilon: float = FLAT_EPSILON) -> Breadth:
    """按截面收益率的符号统计广度；非有限值不参与统计。"""

    up = down = flat = 0
    for value in returns:
        number = float(value)
        if not isfinite(number):
            continue
        if number > epsilon:
            up += 1
        elif number < -epsilon:
            down += 1
        else:
            flat += 1
    return Breadth(up=up, down=down, flat=flat, total=up + down + flat)


@dataclass(frozen=True, slots=True)
class Resonance:
    """共振结论：主导方向与同向占比；`direction=None` 表示没有可判定的截面。"""

    direction: str | None
    strength: float | None
    breadth: Breadth

    @property
    def defined(self) -> bool:
        return self.direction is not None and self.strength is not None


def resonance(returns: Sequence[float], *, epsilon: float = FLAT_EPSILON) -> Resonance:
    """主导方向取上涨/下跌占比的较大者，强度即该方向的成员占比（走平不算同向）。"""

    counts = breadth(returns, epsilon=epsilon)
    if counts.total == 0:
        return Resonance(direction=None, strength=None, breadth=counts)
    up_ratio = counts.up / counts.total
    down_ratio = counts.down / counts.total
    if up_ratio == 0.0 and down_ratio == 0.0:
        return Resonance(direction=None, strength=None, breadth=counts)
    if up_ratio >= down_ratio:
        return Resonance(direction="long", strength=up_ratio, breadth=counts)
    return Resonance(direction="short", strength=down_ratio, breadth=counts)


@dataclass(frozen=True, slots=True)
class CorrelationShift:
    """相关性突变判定：基线段相关系数 vs 最近窗口相关系数。"""

    defined: bool
    flagged: bool
    window: int
    baseline: float | None
    recent: float | None
    delta: float | None


def correlation_shift(
    x: Sequence[float],
    y: Sequence[float],
    *,
    window: int,
    min_abs: float = 0.7,
    min_delta: float = 0.4,
) -> CorrelationShift:
    """检测「原本不相关、最近突然强相关」。

    `window` 是最近窗口长度；基线取 `[0, n-window)`。两段都必须有至少
    `MIN_SAMPLES` 个样本，否则 `defined=False`，不臆造突变结论。
    """

    xs = [float(value) for value in x]
    ys = [float(value) for value in y]
    size = min(len(xs), len(ys))
    if window < MIN_SAMPLES or size - window < MIN_SAMPLES:
        return CorrelationShift(False, False, window, None, None, None)
    xs = xs[:size]
    ys = ys[:size]
    baseline = pearson(xs[: size - window], ys[: size - window])
    recent = pearson(xs[size - window :], ys[size - window :])
    if baseline is None or recent is None:
        return CorrelationShift(False, False, window, baseline, recent, None)
    delta = abs(recent) - abs(baseline)
    flagged = abs(recent) >= min_abs and delta >= min_delta
    return CorrelationShift(True, flagged, window, baseline, recent, delta)


__all__ = [
    "FLAT_EPSILON",
    "Breadth",
    "CorrelationShift",
    "Resonance",
    "breadth",
    "correlation_shift",
    "resonance",
]

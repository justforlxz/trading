"""相对强弱（纯函数）：比值序列、动量与区间超额收益。

口径（`docs/architecture/data-model.md` §3 / api-contract §3.3）：

- `rs_ratio = (P_t / C_t) / (P_0 / C_0)`：窗口起点归一为 1，>1 表示目标跑赢对手；
- `rs_momentum = rs_ratio_now / rs_ratio_{now - momentum_bars} - 1`；
- `excess_return = target_return - counterparty_return`（同一窗口的区间收益差）。

窗口不足或价格非正时返回 `defined=False` 且 `reason` 非空，绝不截断硬算、
绝不返回 NaN。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

REASON_INSUFFICIENT = "insufficient_window"
REASON_NON_POSITIVE = "non_positive_price"
REASON_LENGTH_MISMATCH = "length_mismatch"

TREND_RISING = "rising"
TREND_FALLING = "falling"
TREND_FLAT = "flat"

# 动量绝对值小于该阈值视为持平（浮点噪声，不是业务信号）。
FLAT_EPSILON = 1e-12

MIN_BARS = 2


@dataclass(frozen=True, slots=True)
class RelativeStrength:
    """一次相对强弱计算的结果；未定义字段全部为 `None`。"""

    defined: bool
    reason: str | None
    rs_ratio: float | None
    rs_momentum: float | None
    momentum_reason: str | None
    target_return: float | None
    counterparty_return: float | None
    excess_return: float | None
    trend: str | None


def _undefined(reason: str) -> RelativeStrength:
    return RelativeStrength(
        defined=False,
        reason=reason,
        rs_ratio=None,
        rs_momentum=None,
        momentum_reason=reason,
        target_return=None,
        counterparty_return=None,
        excess_return=None,
        trend=None,
    )


def _check(values: Sequence[float]) -> str | None:
    for value in values:
        if not isfinite(value) or value <= 0.0:
            return REASON_NON_POSITIVE
    return None


def ratio_series(
    target_closes: Sequence[float], counterparty_closes: Sequence[float]
) -> list[float] | None:
    """归一化的比值序列（起点为 1）；长度不一致或价格非正返回 `None`。"""

    if len(target_closes) != len(counterparty_closes) or len(target_closes) < MIN_BARS:
        return None
    targets = [float(value) for value in target_closes]
    others = [float(value) for value in counterparty_closes]
    if _check(targets) is not None or _check(others) is not None:
        return None
    base = targets[0] / others[0]
    if base <= 0.0:
        return None
    return [(target / other) / base for target, other in zip(targets, others, strict=True)]


def compute(
    target_closes: Sequence[float],
    counterparty_closes: Sequence[float],
    *,
    momentum_bars: int,
) -> RelativeStrength:
    """计算相对强弱；`momentum_bars` 由调用方显式给出以保证可复现。"""

    if momentum_bars < 1:
        raise ValueError("momentum_bars must be positive")
    if len(target_closes) != len(counterparty_closes):
        return _undefined(REASON_LENGTH_MISMATCH)
    if len(target_closes) < MIN_BARS:
        return _undefined(REASON_INSUFFICIENT)

    targets = [float(value) for value in target_closes]
    others = [float(value) for value in counterparty_closes]
    invalid = _check(targets) or _check(others)
    if invalid is not None:
        return _undefined(invalid)

    series = ratio_series(targets, others)
    if series is None:  # pragma: no cover - 上面的校验已覆盖
        return _undefined(REASON_NON_POSITIVE)

    rs_ratio = series[-1]
    target_return = targets[-1] / targets[0] - 1.0
    counterparty_return = others[-1] / others[0] - 1.0
    excess_return = target_return - counterparty_return

    momentum_index = len(series) - 1 - momentum_bars
    if momentum_index < 0:
        return RelativeStrength(
            defined=True,
            reason=None,
            rs_ratio=rs_ratio,
            rs_momentum=None,
            momentum_reason=REASON_INSUFFICIENT,
            target_return=target_return,
            counterparty_return=counterparty_return,
            excess_return=excess_return,
            trend=None,
        )

    baseline = series[momentum_index]
    if baseline <= 0.0:  # pragma: no cover - 起点已保证为正
        return _undefined(REASON_NON_POSITIVE)
    rs_momentum = rs_ratio / baseline - 1.0
    if rs_momentum > FLAT_EPSILON:
        trend = TREND_RISING
    elif rs_momentum < -FLAT_EPSILON:
        trend = TREND_FALLING
    else:
        trend = TREND_FLAT
    return RelativeStrength(
        defined=True,
        reason=None,
        rs_ratio=rs_ratio,
        rs_momentum=rs_momentum,
        momentum_reason=None,
        target_return=target_return,
        counterparty_return=counterparty_return,
        excess_return=excess_return,
        trend=trend,
    )


__all__ = [
    "FLAT_EPSILON",
    "MIN_BARS",
    "REASON_INSUFFICIENT",
    "REASON_LENGTH_MISMATCH",
    "REASON_NON_POSITIVE",
    "TREND_FALLING",
    "TREND_FLAT",
    "TREND_RISING",
    "RelativeStrength",
    "compute",
    "ratio_series",
]

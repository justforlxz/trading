"""最大回撤监控与分级处置（P2-05）。

三级阈值对应三种处置动作：``warn`` → ``reduce`` → ``close``；
未触发任何阈值时动作为 ``none``。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.risk.core.limits import TOLERANCE, ZERO
from app.risk.errors import RiskError

ACTIONS = frozenset({"none", "warn", "reduce", "close"})


@dataclass(frozen=True, slots=True)
class DrawdownThresholds:
    warn: Decimal
    reduce: Decimal
    close: Decimal


@dataclass(frozen=True, slots=True)
class DrawdownVerdict:
    drawdown: Decimal
    action: str
    severity: str | None
    breached: bool


def validate_thresholds(thresholds: DrawdownThresholds) -> None:
    """要求 ``0 < warn < reduce < close``，否则抛 ``risk_invalid_threshold``。"""
    values = (thresholds.warn, thresholds.reduce, thresholds.close)
    if not all(value > ZERO for value in values) or not (
        thresholds.warn < thresholds.reduce < thresholds.close
    ):
        raise RiskError(
            "risk_invalid_threshold",
            "回撤阈值必须满足 0 < warn < reduce < close",
            details={
                "warn": str(thresholds.warn),
                "reduce": str(thresholds.reduce),
                "close": str(thresholds.close),
            },
        )


def drawdown_series(values: tuple[Decimal, ...]) -> tuple[Decimal, Decimal]:
    """返回 (峰值, 区间最大回撤)。"""
    peak = ZERO
    max_drawdown = ZERO
    for value in values:
        if value > peak:
            peak = value
        if peak > ZERO:
            drawdown = (peak - value) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown
    return peak, max_drawdown


def evaluate_drawdown(
    *, equity: Decimal, peak: Decimal, thresholds: DrawdownThresholds
) -> DrawdownVerdict:
    """按当前净值与历史峰值判定处置动作。"""
    if peak <= ZERO or equity < ZERO:
        raise RiskError("risk_invalid_input", "净值与峰值必须为非负数且峰值大于 0")

    drawdown = (peak - equity) / peak
    action = "none"
    severity: str | None = None
    if drawdown + TOLERANCE >= thresholds.close:
        action, severity = "close", "tier3"
    elif drawdown + TOLERANCE >= thresholds.reduce:
        action, severity = "reduce", "tier2"
    elif drawdown + TOLERANCE >= thresholds.warn:
        action, severity = "warn", "tier1"

    return DrawdownVerdict(drawdown, action, severity, action != "none")


__all__ = [
    "ACTIONS",
    "DrawdownThresholds",
    "DrawdownVerdict",
    "drawdown_series",
    "evaluate_drawdown",
    "validate_thresholds",
]

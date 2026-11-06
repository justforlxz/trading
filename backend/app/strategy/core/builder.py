"""策略构建器：把候选腿折算成合法权重与可复核依据（纯函数）。

流程固定：模板打分 → 按分数分配 100% 总敞口（单标的上限用水填充）→ 按方向定符号
→ 约束校验 → 生成 rationale。任何一步不满足都抛 `ConstraintViolation`，
不存在「裁剪一下继续」的分支。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.strategy.core.constraints import ConstraintViolation, check_legs
from app.strategy.core.templates import (
    KNOWN_TEMPLATES,
    TEMPLATES,
    TemplateSignal,
    expand_templates,
    format_rationale,
)

QUANTUM = Decimal("1e-10")
_TOL = Decimal("1e-9")


@dataclass(frozen=True)
class LegCandidate:
    """一个待评估的腿：标的身份、方向与生成所需的具名指标。"""

    instrument_id: int
    inst_id: str
    side: str
    metrics: Mapping[str, Any] = field(default_factory=dict)
    symbol: str | None = None


@dataclass(frozen=True)
class BuiltLeg:
    """构建结果；`target_weight` 有符号，long 为正、short 为负。"""

    instrument_id: int
    inst_id: str
    side: str
    target_weight: Decimal
    rationale: str
    rank: int = 0
    symbol: str | None = None


def select_signal(candidate: LegCandidate, templates: Sequence[str]) -> TemplateSignal:
    """取命中模板里分数最高者；一个都不命中说明该腿无依据，直接拒绝。"""

    best: TemplateSignal | None = None
    for name in templates:
        signal = TEMPLATES[name](candidate.metrics)
        if signal is None or signal.score <= 0.0:
            continue
        if best is None or signal.score > best.score:
            best = signal
    if best is None:
        raise ConstraintViolation(
            "strategy_unevidenced_leg",
            f"no template produced a signal for {candidate.inst_id}",
            details={
                "instrument_id": candidate.instrument_id,
                "inst_id": candidate.inst_id,
                "templates": list(templates),
            },
        )
    return best


def allocate(strengths: Sequence[float], *, cap: Decimal) -> list[Decimal]:
    """按强度分配 100% 总敞口，任一腿不超过 `cap`（水填充）。

    返回值之和严格为 1，且每项是 1e-10 的整数倍（可直接写入 NUMERIC(12,10)）。
    """

    count = len(strengths)
    if count == 0:
        raise ConstraintViolation("strategy_min_legs", "no candidate legs to allocate")
    weights: list[Decimal | None] = [None] * count
    remaining = Decimal(1)
    pending = list(range(count))
    while pending:
        total = sum(strengths[index] for index in pending)
        if total <= 0.0:
            raise ConstraintViolation("strategy_no_signal", "signal strengths sum to zero")
        capped = [
            index
            for index in pending
            if remaining * Decimal(str(strengths[index])) / Decimal(str(total)) > cap + _TOL
        ]
        if not capped:
            for index in pending:
                weights[index] = remaining * Decimal(str(strengths[index])) / Decimal(str(total))
            remaining = Decimal(0)
            pending = []
            break
        for index in capped:
            weights[index] = cap
            remaining -= cap
            pending.remove(index)

    if remaining > _TOL:
        raise ConstraintViolation(
            "strategy_position_limit",
            "position cap too tight to allocate 100% gross exposure",
            details={"max_position_weight": str(cap), "unallocated": str(remaining)},
        )
    if any(weight is None for weight in weights):
        raise ConstraintViolation("strategy_position_limit", "failed to allocate all legs")

    rounded = [weight.quantize(QUANTUM) for weight in weights if weight is not None]
    residual = Decimal(1) - sum(rounded, Decimal(0))
    largest = max(range(len(rounded)), key=lambda index: (rounded[index], -index))
    rounded[largest] += residual
    return rounded


def build_legs(
    candidates: Sequence[LegCandidate],
    *,
    templates: Sequence[str],
    max_position_weight: float | Decimal,
    max_gross_exposure: float | Decimal,
    max_net_exposure: float | Decimal,
    min_legs: int,
    max_legs: int | None,
    window_bars: int | None,
) -> list[BuiltLeg]:
    """生成合法组合；模板名未知、腿无依据、约束越界都抛带 code 的错误。"""

    if not templates:
        raise ConstraintViolation(
            "strategy_templates_required", "at least one template is required"
        )
    unknown = [name for name in templates if name not in KNOWN_TEMPLATES]
    if unknown:
        raise ConstraintViolation(
            "strategy_unknown_template",
            f"unknown templates: {', '.join(sorted(unknown))}",
            details={"unknown": sorted(unknown), "known": list(KNOWN_TEMPLATES)},
        )
    effective = expand_templates(templates)

    count = len(candidates)
    if count < min_legs:
        raise ConstraintViolation(
            "strategy_min_legs",
            f"strategy needs at least {min_legs} legs, got {count}",
            details={"min_legs": min_legs, "legs": count},
        )
    if max_legs is not None and count > max_legs:
        raise ConstraintViolation(
            "strategy_max_legs",
            f"strategy allows at most {max_legs} legs, got {count}",
            details={"max_legs": max_legs, "legs": count},
        )

    seen: set[int] = set()
    for candidate in candidates:
        if candidate.side not in ("long", "short"):
            raise ConstraintViolation(
                "strategy_invalid_side",
                f"unknown side {candidate.side!r} on {candidate.inst_id}",
                details={"instrument_id": candidate.instrument_id, "side": candidate.side},
            )
        if candidate.instrument_id in seen:
            raise ConstraintViolation(
                "strategy_duplicate_leg",
                f"instrument {candidate.instrument_id} appears more than once",
                details={"instrument_id": candidate.instrument_id},
            )
        seen.add(candidate.instrument_id)

    signals = [select_signal(candidate, effective) for candidate in candidates]
    cap = Decimal(str(max_position_weight))
    magnitudes = allocate([signal.score for signal in signals], cap=cap)

    legs: list[BuiltLeg] = []
    for candidate, signal, magnitude in zip(candidates, signals, magnitudes, strict=True):
        signed = magnitude if candidate.side == "long" else -magnitude
        legs.append(
            BuiltLeg(
                instrument_id=candidate.instrument_id,
                inst_id=candidate.inst_id,
                side=candidate.side,
                target_weight=signed,
                rationale=format_rationale(
                    signal.basis, window_bars=window_bars, template=signal.template
                ),
                symbol=candidate.symbol,
            )
        )

    legs.sort(key=lambda leg: (-abs(leg.target_weight), leg.instrument_id))
    legs = [
        BuiltLeg(
            instrument_id=leg.instrument_id,
            inst_id=leg.inst_id,
            side=leg.side,
            target_weight=leg.target_weight,
            rationale=leg.rationale,
            rank=index + 1,
            symbol=leg.symbol,
        )
        for index, leg in enumerate(legs)
    ]

    check_legs(
        legs,
        min_legs=min_legs,
        max_legs=max_legs,
        max_position_weight=max_position_weight,
        max_gross_exposure=max_gross_exposure,
        max_net_exposure=max_net_exposure,
    )
    return legs


__all__ = ["BuiltLeg", "LegCandidate", "allocate", "build_legs", "select_signal"]

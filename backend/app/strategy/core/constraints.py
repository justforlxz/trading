"""组合权重约束（纯函数）。

约束越界一律抛 `ConstraintViolation` 并带明确 `code`，绝不静默裁剪或换个权重
继续。调用方把 `code` 原样放进 API 错误体，前端与测试都能据此断言。
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

TOL = Decimal("1e-9")


@runtime_checkable
class WeightedLeg(Protocol):
    """约束校验只需这三项；`builder.BuiltLeg` 与 ORM 模型都满足。"""

    instrument_id: int
    side: str
    target_weight: Any


class ConstraintViolation(Exception):
    """领域错误：`code` 原样进入 API 错误体，`status_code` 决定 HTTP 状态码。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


def _weight(leg: WeightedLeg) -> Decimal:
    return Decimal(str(leg.target_weight))


def gross_exposure(legs: Sequence[WeightedLeg]) -> Decimal:
    return sum((abs(_weight(leg)) for leg in legs), Decimal(0))


def net_exposure(legs: Sequence[WeightedLeg]) -> Decimal:
    return sum((_weight(leg) for leg in legs), Decimal(0))


def check_legs(
    legs: Sequence[WeightedLeg],
    *,
    min_legs: int,
    max_legs: int | None,
    max_position_weight: float | Decimal,
    max_gross_exposure: float | Decimal,
    max_net_exposure: float | Decimal,
) -> None:
    """逐条校验组合合法性；任一不满足即抛错，不做任何修补。"""

    count = len(legs)
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
    for leg in legs:
        if leg.instrument_id in seen:
            raise ConstraintViolation(
                "strategy_duplicate_leg",
                f"instrument {leg.instrument_id} appears more than once",
                details={"instrument_id": leg.instrument_id},
            )
        seen.add(leg.instrument_id)

    position_cap = Decimal(str(max_position_weight))
    for leg in legs:
        if leg.side not in ("long", "short"):
            raise ConstraintViolation(
                "strategy_invalid_side",
                f"unknown side {leg.side!r} on instrument {leg.instrument_id}",
                details={"instrument_id": leg.instrument_id, "side": leg.side},
            )
        weight = _weight(leg)
        if leg.side == "long" and weight <= 0:
            raise ConstraintViolation(
                "strategy_side_weight_mismatch",
                f"long leg {leg.instrument_id} must have a positive weight",
                details={
                    "instrument_id": leg.instrument_id,
                    "side": leg.side,
                    "weight": str(weight),
                },
            )
        if leg.side == "short" and weight >= 0:
            raise ConstraintViolation(
                "strategy_side_weight_mismatch",
                f"short leg {leg.instrument_id} must have a negative weight",
                details={
                    "instrument_id": leg.instrument_id,
                    "side": leg.side,
                    "weight": str(weight),
                },
            )
        if abs(weight) > position_cap + TOL:
            raise ConstraintViolation(
                "strategy_position_limit",
                f"instrument {leg.instrument_id} weight {weight} exceeds {position_cap}",
                details={
                    "instrument_id": leg.instrument_id,
                    "weight": str(weight),
                    "max_position_weight": str(position_cap),
                },
            )

    gross = gross_exposure(legs)
    if abs(gross - Decimal(1)) > TOL:
        raise ConstraintViolation(
            "strategy_gross_not_normalized",
            f"sum(abs(weight)) must be 1.0, got {gross}",
            details={"gross_exposure": str(gross)},
        )
    gross_cap = Decimal(str(max_gross_exposure))
    if gross > gross_cap + TOL:
        raise ConstraintViolation(
            "strategy_gross_exposure_exceeded",
            f"gross exposure {gross} exceeds cap {gross_cap}",
            details={"gross_exposure": str(gross), "max_gross_exposure": str(gross_cap)},
        )

    net = abs(net_exposure(legs))
    net_cap = Decimal(str(max_net_exposure))
    if net > net_cap + TOL:
        raise ConstraintViolation(
            "strategy_net_exposure_exceeded",
            f"net exposure {net} exceeds cap {net_cap}",
            details={"net_exposure": str(net), "max_net_exposure": str(net_cap)},
        )


__all__ = [
    "ConstraintViolation",
    "WeightedLeg",
    "check_legs",
    "gross_exposure",
    "net_exposure",
]

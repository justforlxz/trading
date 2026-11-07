"""策略级限额校验（P2-02）。

纯函数：输入腿意图、限额与资金，输出判决。任何不确定的输入都返回
``ok=False`` 的判决，调用方只能在 ``ok=True`` 时放行增加敞口。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal("0")
TOLERANCE = Decimal("1e-9")
SIDES = frozenset({"long", "short"})


def _exceeds(observed: Decimal, threshold: Decimal) -> bool:
    """严格超过阈值才判越限；等于阈值（含 1e-9 容差）视为通过。"""
    return observed > threshold + TOLERANCE


@dataclass(frozen=True, slots=True)
class Limits:
    """单策略限额集合，金额为计价货币，比例为资金占比。"""

    max_order_notional: Decimal
    max_leg_weight: Decimal
    max_leverage: Decimal
    max_gross_exposure: Decimal
    max_net_exposure: Decimal
    max_instrument_weight: Decimal
    max_concentration: Decimal


@dataclass(frozen=True, slots=True)
class LegIntent:
    """一条待评估腿：方向、目标权重与折算后的名义金额。"""

    instrument_id: int
    side: str
    weight: Decimal
    notional: Decimal


@dataclass(frozen=True, slots=True)
class Breach:
    code: str
    field: str
    observed: Decimal
    threshold: Decimal


@dataclass(frozen=True, slots=True)
class LimitVerdict:
    ok: bool
    gross_exposure: Decimal
    net_exposure: Decimal
    leverage: Decimal
    breaches: tuple[Breach, ...]


def _denied(breaches: list[Breach]) -> LimitVerdict:
    return LimitVerdict(False, ZERO, ZERO, ZERO, tuple(breaches))


def evaluate_limits(
    *, legs: tuple[LegIntent, ...], limits: Limits, capital: Decimal
) -> LimitVerdict:
    """校验一组腿是否在单策略限额之内。"""
    breaches: list[Breach] = []

    if capital <= ZERO:
        breaches.append(Breach("risk_insufficient_capital", "capital", capital, ZERO))
        return _denied(breaches)
    if not legs:
        breaches.append(Breach("risk_empty_portfolio", "legs", ZERO, Decimal("1")))
        return _denied(breaches)

    for leg in legs:
        if leg.side not in SIDES:
            breaches.append(Breach("risk_invalid_side", f"side:{leg.instrument_id}", ZERO, ZERO))
        if leg.weight < ZERO:
            breaches.append(
                Breach("risk_invalid_weight", f"weight:{leg.instrument_id}", leg.weight, ZERO)
            )
        if leg.notional < ZERO:
            breaches.append(
                Breach("risk_invalid_weight", f"notional:{leg.instrument_id}", leg.notional, ZERO)
            )
    if breaches:
        return _denied(breaches)

    gross = sum((leg.notional for leg in legs), ZERO)
    signed = sum(
        (leg.notional if leg.side == "long" else -leg.notional for leg in legs),
        ZERO,
    )
    net = abs(signed)
    gross_ratio = gross / capital
    net_ratio = net / capital
    leverage = gross / capital

    per_instrument: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for leg in legs:
        per_instrument[leg.instrument_id] += leg.weight

    for leg in legs:
        if _exceeds(leg.notional, limits.max_order_notional):
            breaches.append(
                Breach(
                    "order_notional_exceeded",
                    f"notional:{leg.instrument_id}",
                    leg.notional,
                    limits.max_order_notional,
                )
            )
        if _exceeds(leg.weight, limits.max_leg_weight):
            breaches.append(
                Breach(
                    "leg_weight_exceeded",
                    f"weight:{leg.instrument_id}",
                    leg.weight,
                    limits.max_leg_weight,
                )
            )
    for instrument_id in sorted(per_instrument):
        weight = per_instrument[instrument_id]
        if _exceeds(weight, limits.max_instrument_weight):
            breaches.append(
                Breach(
                    "instrument_weight_exceeded",
                    f"instrument:{instrument_id}",
                    weight,
                    limits.max_instrument_weight,
                )
            )
        if _exceeds(weight, limits.max_concentration):
            breaches.append(
                Breach(
                    "concentration_exceeded",
                    f"instrument:{instrument_id}",
                    weight,
                    limits.max_concentration,
                )
            )
    if _exceeds(gross_ratio, limits.max_gross_exposure):
        breaches.append(
            Breach(
                "gross_exposure_exceeded",
                "gross_exposure",
                gross_ratio,
                limits.max_gross_exposure,
            )
        )
    if _exceeds(net_ratio, limits.max_net_exposure):
        breaches.append(
            Breach(
                "net_exposure_exceeded",
                "net_exposure",
                net_ratio,
                limits.max_net_exposure,
            )
        )
    if _exceeds(leverage, limits.max_leverage):
        breaches.append(Breach("leverage_exceeded", "leverage", leverage, limits.max_leverage))

    return LimitVerdict(not breaches, gross, net, leverage, tuple(breaches))


__all__ = [
    "SIDES",
    "TOLERANCE",
    "ZERO",
    "Breach",
    "LegIntent",
    "LimitVerdict",
    "Limits",
    "evaluate_limits",
]

"""全局组合风险（P2-03）。

把多个策略的虚拟持仓聚合成一个全局组合，计算总敞口、净敞口、集中度、
多空冲突与跨策略重复持仓。权重口径为「占组合资金的比例」。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from app.risk.core.limits import ZERO, Breach, Limits, _exceeds
from app.risk.errors import RiskError


@dataclass(frozen=True, slots=True)
class Position:
    strategy_id: int
    instrument_id: int
    side: str
    weight: Decimal
    notional: Decimal


@dataclass(frozen=True, slots=True)
class DuplicateHolding:
    instrument_id: int
    side: str
    strategy_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PortfolioRisk:
    gross_exposure: Decimal
    net_exposure: Decimal
    long_exposure: Decimal
    short_exposure: Decimal
    concentration: Decimal
    instrument_weights: dict[int, Decimal]
    long_short_conflicts: tuple[int, ...]
    duplicates: tuple[DuplicateHolding, ...]


def evaluate_portfolio(positions: tuple[Position, ...], *, capital: Decimal) -> PortfolioRisk:
    """聚合组合风险指标。

    ``capital <= 0`` 时抛 :class:`RiskError`，由调用方按 fail-closed 拒绝放行。
    """
    if capital <= ZERO:
        raise RiskError("risk_insufficient_capital", "组合资金必须为正数")

    gross = ZERO
    long_total = ZERO
    short_total = ZERO
    weights: dict[int, Decimal] = defaultdict(lambda: ZERO)
    sides: dict[int, set[str]] = defaultdict(set)
    holders: dict[tuple[int, str], set[int]] = defaultdict(set)

    for position in positions:
        gross += position.notional
        weights[position.instrument_id] += position.weight
        sides[position.instrument_id].add(position.side)
        holders[(position.instrument_id, position.side)].add(position.strategy_id)
        if position.side == "short":
            short_total += position.notional
        else:
            long_total += position.notional

    concentration = max(weights.values(), default=ZERO)
    conflicts = tuple(sorted(iid for iid, values in sides.items() if len(values) > 1))
    duplicates = tuple(
        DuplicateHolding(instrument_id, side, tuple(sorted(strategy_ids)))
        for (instrument_id, side), strategy_ids in sorted(holders.items())
        if len(strategy_ids) > 1
    )
    return PortfolioRisk(
        gross_exposure=gross,
        net_exposure=abs(long_total - short_total),
        long_exposure=long_total,
        short_exposure=short_total,
        concentration=concentration,
        instrument_weights=dict(sorted(weights.items())),
        long_short_conflicts=conflicts,
        duplicates=duplicates,
    )


def portfolio_breaches(
    risk: PortfolioRisk, limits: Limits, *, capital: Decimal
) -> tuple[Breach, ...]:
    """把组合指标与全局限额比对，返回越限列表。"""
    if capital <= ZERO:
        return (Breach("risk_insufficient_capital", "capital", capital, ZERO),)

    breaches: list[Breach] = []
    gross_ratio = risk.gross_exposure / capital
    net_ratio = risk.net_exposure / capital
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
            Breach("net_exposure_exceeded", "net_exposure", net_ratio, limits.max_net_exposure)
        )
    if _exceeds(risk.concentration, limits.max_concentration):
        breaches.append(
            Breach(
                "concentration_exceeded",
                "concentration",
                risk.concentration,
                limits.max_concentration,
            )
        )
    for instrument_id, weight in risk.instrument_weights.items():
        if _exceeds(weight, limits.max_instrument_weight):
            breaches.append(
                Breach(
                    "instrument_weight_exceeded",
                    f"instrument:{instrument_id}",
                    weight,
                    limits.max_instrument_weight,
                )
            )
    return tuple(breaches)


__all__ = [
    "DuplicateHolding",
    "PortfolioRisk",
    "Position",
    "evaluate_portfolio",
    "portfolio_breaches",
]

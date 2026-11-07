"""自动资金分配（P2-04）。

按优先级从高到低分配总预算，保证三条不变式：

1. 所有分配之和不超过总预算；
2. 单个策略拿到的资金不超过其申请预算；
3. 高优先级策略不会因为低优先级先到而被饿死。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.risk.core.limits import ZERO


@dataclass(frozen=True, slots=True)
class AllocationRequest:
    strategy_id: int
    priority: int
    budget: Decimal
    min_order_notional: Decimal


@dataclass(frozen=True, slots=True)
class Allocation:
    strategy_id: int
    budget: Decimal
    skipped: bool
    reason: str | None


def allocate(
    total_budget: Decimal, requests: tuple[AllocationRequest, ...]
) -> tuple[Allocation, ...]:
    """按 ``(-priority, strategy_id)`` 顺序贪心分配。"""
    ordered = sorted(requests, key=lambda item: (-item.priority, item.strategy_id))
    remaining = total_budget if total_budget > ZERO else ZERO
    results: list[Allocation] = []

    for request in ordered:
        if request.budget <= ZERO:
            results.append(Allocation(request.strategy_id, ZERO, True, "invalid_budget"))
            continue
        if total_budget <= ZERO or remaining <= ZERO:
            results.append(Allocation(request.strategy_id, ZERO, True, "budget_exhausted"))
            continue
        grant = min(request.budget, remaining)
        if grant < request.min_order_notional:
            results.append(Allocation(request.strategy_id, ZERO, True, "below_min_order_notional"))
            continue
        remaining -= grant
        results.append(Allocation(request.strategy_id, grant, False, None))

    return tuple(results)


__all__ = ["Allocation", "AllocationRequest", "allocate"]

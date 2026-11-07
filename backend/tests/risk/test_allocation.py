"""自动资金分配纯函数用例（P2-04）：三条不变式 + 预算不足分支。"""

from decimal import Decimal

from app.risk.core.allocation import AllocationRequest, allocate


def _request(
    strategy_id: int,
    priority: int,
    budget: str,
    min_order_notional: str = "1000",
) -> AllocationRequest:
    return AllocationRequest(
        strategy_id=strategy_id,
        priority=priority,
        budget=Decimal(budget),
        min_order_notional=Decimal(min_order_notional),
    )


def test_allocations_never_exceed_budget_or_request() -> None:
    requests = (
        _request(1, 10, "60000"),
        _request(2, 5, "60000"),
        _request(3, 1, "60000"),
    )
    result = allocate(Decimal("100000"), requests)

    total = sum(item.budget for item in result)
    assert total == Decimal("100000")
    assert total <= Decimal("100000")
    for allocation, request in zip(
        result, sorted(requests, key=lambda r: (-r.priority, r.strategy_id)), strict=True
    ):
        assert allocation.budget <= request.budget


def test_high_priority_gets_funded_first() -> None:
    requests = (
        _request(1, 1, "80000"),
        _request(2, 10, "50000"),
    )
    result = allocate(Decimal("100000"), requests)
    by_strategy = {item.strategy_id: item for item in result}
    assert by_strategy[2].budget == Decimal("50000")
    assert by_strategy[1].budget == Decimal("50000")
    assert by_strategy[1].skipped is False


def test_exhausted_budget_marks_lower_priority_skipped() -> None:
    requests = (_request(1, 10, "100000"), _request(2, 5, "10000"))
    result = allocate(Decimal("100000"), requests)
    lower = next(item for item in result if item.strategy_id == 2)
    assert lower.budget == Decimal("0")
    assert lower.skipped is True
    assert lower.reason == "budget_exhausted"


def test_below_min_order_notional_is_skipped_without_spending_budget() -> None:
    requests = (
        _request(1, 10, "500", min_order_notional="1000"),
        _request(2, 5, "50000"),
    )
    result = allocate(Decimal("100000"), requests)
    small = next(item for item in result if item.strategy_id == 1)
    normal = next(item for item in result if item.strategy_id == 2)
    assert small.skipped is True
    assert small.reason == "below_min_order_notional"
    assert small.budget == Decimal("0")
    assert normal.budget == Decimal("50000")


def test_zero_total_budget_allocates_nothing() -> None:
    result = allocate(Decimal("0"), (_request(1, 10, "1000"),))
    assert result[0].budget == Decimal("0")
    assert result[0].reason == "budget_exhausted"


def test_invalid_request_budget_is_flagged() -> None:
    result = allocate(Decimal("100000"), (_request(1, 10, "0"),))
    assert result[0].skipped is True
    assert result[0].reason == "invalid_budget"


def test_empty_requests_returns_empty_tuple() -> None:
    assert allocate(Decimal("100000"), ()) == ()

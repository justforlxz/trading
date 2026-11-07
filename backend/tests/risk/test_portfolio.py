"""全局组合风险纯函数用例（P2-03）：所有期望值手算并保留 1e-9 精度。"""

from decimal import Decimal

import pytest

from app.risk.core.limits import Limits
from app.risk.core.portfolio import (
    DuplicateHolding,
    Position,
    evaluate_portfolio,
    portfolio_breaches,
)
from app.risk.errors import RiskError

CAPITAL = Decimal("100000")

POSITIONS = (
    Position(
        strategy_id=1,
        instrument_id=10,
        side="long",
        weight=Decimal("0.30"),
        notional=Decimal("30000"),
    ),
    Position(
        strategy_id=2,
        instrument_id=10,
        side="short",
        weight=Decimal("0.20"),
        notional=Decimal("20000"),
    ),
    Position(
        strategy_id=1,
        instrument_id=20,
        side="long",
        weight=Decimal("0.25"),
        notional=Decimal("25000"),
    ),
    Position(
        strategy_id=2,
        instrument_id=20,
        side="long",
        weight=Decimal("0.15"),
        notional=Decimal("15000"),
    ),
)


def _limits(**overrides: str) -> Limits:
    values = {
        "max_order_notional": Decimal("100000"),
        "max_leg_weight": Decimal("1.0"),
        "max_leverage": Decimal("1.0"),
        "max_gross_exposure": Decimal("1.0"),
        "max_net_exposure": Decimal("1.0"),
        "max_instrument_weight": Decimal("0.6"),
        "max_concentration": Decimal("0.5"),
    }
    values.update({key: Decimal(value) for key, value in overrides.items()})
    return Limits(**values)


def test_aggregates_match_hand_computation() -> None:
    risk = evaluate_portfolio(POSITIONS, capital=CAPITAL)
    assert risk.gross_exposure == Decimal("90000")
    assert risk.long_exposure == Decimal("70000")
    assert risk.short_exposure == Decimal("20000")
    assert risk.net_exposure == Decimal("50000")
    assert risk.instrument_weights == {10: Decimal("0.50"), 20: Decimal("0.40")}
    assert risk.concentration == Decimal("0.50")


def test_identifies_long_short_conflict() -> None:
    risk = evaluate_portfolio(POSITIONS, capital=CAPITAL)
    assert risk.long_short_conflicts == (10,)


def test_identifies_cross_strategy_duplicate_holding() -> None:
    risk = evaluate_portfolio(POSITIONS, capital=CAPITAL)
    assert risk.duplicates == (DuplicateHolding(20, "long", (1, 2)),)


def test_empty_portfolio_is_zero() -> None:
    risk = evaluate_portfolio((), capital=CAPITAL)
    assert risk.gross_exposure == Decimal("0")
    assert risk.net_exposure == Decimal("0")
    assert risk.concentration == Decimal("0")
    assert risk.long_short_conflicts == ()
    assert risk.duplicates == ()


def test_non_positive_capital_raises() -> None:
    with pytest.raises(RiskError) as excinfo:
        evaluate_portfolio(POSITIONS, capital=Decimal("0"))
    assert excinfo.value.code == "risk_insufficient_capital"


def test_no_breach_at_exact_thresholds() -> None:
    risk = evaluate_portfolio(POSITIONS, capital=CAPITAL)
    assert portfolio_breaches(risk, _limits(), capital=CAPITAL) == ()


def test_concentration_breach_detected() -> None:
    risk = evaluate_portfolio(POSITIONS, capital=CAPITAL)
    breaches = portfolio_breaches(risk, _limits(max_concentration="0.4"), capital=CAPITAL)
    assert [item.code for item in breaches] == ["concentration_exceeded"]
    assert breaches[0].observed == Decimal("0.50")
    assert breaches[0].threshold == Decimal("0.4")


def test_gross_and_instrument_breaches_detected() -> None:
    risk = evaluate_portfolio(POSITIONS, capital=CAPITAL)
    breaches = portfolio_breaches(
        risk, _limits(max_gross_exposure="0.8", max_instrument_weight="0.45"), capital=CAPITAL
    )
    codes = {item.code for item in breaches}
    assert {"gross_exposure_exceeded", "instrument_weight_exceeded"} <= codes


def test_deterministic_ordering() -> None:
    first = evaluate_portfolio(POSITIONS, capital=CAPITAL)
    second = evaluate_portfolio(POSITIONS, capital=CAPITAL)
    assert first == second
    assert list(first.instrument_weights) == sorted(first.instrument_weights)

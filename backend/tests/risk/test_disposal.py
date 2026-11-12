"""分级处置的纯函数：三档 × 适用类别的九种情形与类别门禁。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.risk import (
    DisposalAction,
    DisposalContext,
    Severity,
    plan,
)
from app.risk.disposal import (
    RULE_AVAILABLE_BALANCE,
    RULE_DRAWDOWN,
    RULE_FUNDING,
    RULE_INSTRUMENT_WEIGHT,
    RULE_LIQUIDATION,
    RULE_MARGIN_INSUFFICIENT,
    RULE_ORDER_AMOUNT,
)
from app.risk.rules import RiskLimits

D = Decimal

SPOT = "SPOT"
SWAP = "SWAP"
SPOT_ID = "XAAPL-USDT"
SWAP_ID = "AAPL-USDT-SWAP"
PRODUCT = "AAPL"


def context(inst_type: str, **overrides: object) -> DisposalContext:
    values: dict[str, object] = {
        "inst_type": inst_type,
        "inst_id": SPOT_ID if inst_type == SPOT else SWAP_ID,
        "product_key": PRODUCT,
        "equity": D("10000"),
        "strategy_equity": D("10000"),
    }
    values.update(overrides)
    return DisposalContext(**values)  # type: ignore[arg-type]


CASES = [
    pytest.param(
        RULE_INSTRUMENT_WEIGHT,
        context(SPOT, instrument_weight=D("3300")),
        Severity.LIGHT,
        (DisposalAction.WARN,),
        id="light-shared-weight",
    ),
    pytest.param(
        RULE_FUNDING,
        context(SWAP, funding_rate=D("0.0125")),
        Severity.LIGHT,
        (DisposalAction.WARN,),
        id="light-swap-funding",
    ),
    pytest.param(
        RULE_AVAILABLE_BALANCE,
        context(SPOT, available_balance=D("1500")),
        Severity.LIGHT,
        (DisposalAction.WARN,),
        id="light-spot-balance",
    ),
    pytest.param(
        RULE_DRAWDOWN,
        context(SPOT, drawdown=D("0.10")),
        Severity.MEDIUM,
        (DisposalAction.REDUCE,),
        id="medium-shared-drawdown",
    ),
    pytest.param(
        RULE_LIQUIDATION,
        context(SWAP, liquidation_distance=D("0.075")),
        Severity.MEDIUM,
        (DisposalAction.REDUCE,),
        id="medium-swap-liquidation",
    ),
    pytest.param(
        RULE_AVAILABLE_BALANCE,
        context(SPOT, available_balance=D("700")),
        Severity.MEDIUM,
        (DisposalAction.REDUCE,),
        id="medium-spot-balance",
    ),
    pytest.param(
        RULE_DRAWDOWN,
        context(SPOT, drawdown=D("0.20")),
        Severity.SEVERE,
        (DisposalAction.STOP_LOSS, DisposalAction.HALT_ALL),
        id="severe-shared-drawdown",
    ),
    pytest.param(
        RULE_LIQUIDATION,
        context(SWAP, liquidation_distance=D("0.03")),
        Severity.SEVERE,
        (DisposalAction.STOP_LOSS, DisposalAction.LIQUIDATE),
        id="severe-swap-liquidation",
    ),
    pytest.param(
        RULE_AVAILABLE_BALANCE,
        context(SPOT, available_balance=D("300")),
        Severity.SEVERE,
        (DisposalAction.LIQUIDATE,),
        id="severe-spot-balance",
    ),
]


@pytest.mark.parametrize(("rule", "facts", "severity", "actions"), CASES)
def test_three_severities_across_applicable_categories(
    rule: str,
    facts: DisposalContext,
    severity: Severity,
    actions: tuple[DisposalAction, ...],
) -> None:
    result = plan(rule, facts)

    assert result is not None
    assert result.severity is severity
    assert result.actions == actions
    assert result.inst_id == facts.inst_id
    assert result.product_key == facts.product_key


def test_funding_above_the_limit_is_always_light() -> None:
    for rate in ("0.02", "0.05"):
        result = plan(RULE_FUNDING, context(SWAP, funding_rate=D(rate)))

        assert result is not None
        assert result.severity is Severity.LIGHT
        assert result.actions == (DisposalAction.WARN,)


def test_margin_insufficient_is_severe_only_for_margin_instruments() -> None:
    assert plan(RULE_MARGIN_INSUFFICIENT, context(SPOT)) is None

    result = plan(RULE_MARGIN_INSUFFICIENT, context(SWAP))

    assert result is not None
    assert result.severity is Severity.SEVERE
    assert result.actions == (DisposalAction.STOP_LOSS, DisposalAction.LIQUIDATE)


def test_zero_strategy_budget_does_not_fall_back_to_portfolio_equity() -> None:
    result = plan(RULE_ORDER_AMOUNT, context(SPOT, strategy_equity=D("0"), order_amount=D("1")))

    assert result is not None
    assert result.severity is Severity.MEDIUM


def test_zero_thresholds_still_produce_disposals() -> None:
    drawdown = plan(
        RULE_DRAWDOWN,
        context(SPOT, drawdown=D("0.01"), limits=RiskLimits(max_drawdown=D("0"))),
    )
    funding = plan(
        RULE_FUNDING,
        context(SWAP, funding_rate=D("0.001"), limits=RiskLimits(max_funding_rate=D("0"))),
    )
    liquidation = plan(
        RULE_LIQUIDATION,
        context(
            SWAP,
            liquidation_distance=D("-0.01"),
            limits=RiskLimits(min_liquidation_distance=D("0")),
        ),
    )

    assert drawdown is not None
    assert drawdown.severity is Severity.SEVERE
    assert funding is not None
    assert funding.severity is Severity.LIGHT
    assert liquidation is not None
    assert liquidation.severity is Severity.SEVERE


def test_spot_ignores_funding_and_liquidation_rules() -> None:
    assert plan(RULE_FUNDING, context(SPOT, funding_rate=D("1"))) is None
    assert plan(RULE_LIQUIDATION, context(SPOT, liquidation_distance=D("0"))) is None


def test_swap_ignores_spot_available_balance_rule() -> None:
    assert plan(RULE_AVAILABLE_BALANCE, context(SWAP, available_balance=D("1"))) is None


def test_below_the_first_threshold_has_no_plan() -> None:
    assert plan(RULE_DRAWDOWN, context(SPOT, drawdown=D("0.05"))) is None
    assert plan(RULE_LIQUIDATION, context(SWAP, liquidation_distance=D("0.20"))) is None
    assert plan(RULE_AVAILABLE_BALANCE, context(SPOT, available_balance=D("5000"))) is None


def test_unknown_rule_is_rejected_instead_of_silently_ignored() -> None:
    with pytest.raises(Exception, match="未知的处置规则"):
        plan("not_a_rule", context(SPOT))

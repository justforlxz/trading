"""风控规则：两层限制、按类别适用与逐条触发。

这里的判定全部是纯函数：不连库、不产生订单，只回答「哪些规则适用、哪几条被触发」。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.instrument import Instrument
from app.risk import (
    Correlation,
    PositionExposure,
    RiskContext,
    RiskLimits,
    SignalRecord,
    TradeRequest,
    applicable_rule_names,
    evaluate,
    rule_applicability,
)

D = Decimal
NOW = datetime(2026, 11, 13, 2, 0, tzinfo=UTC)


def spot_instrument(*, lot_size: D = D("0.01")) -> Instrument:
    return Instrument(
        symbol="XAAPL-USDT",
        inst_type="SPOT",
        product_key="AAPL",
        asset_type="tokenized_equity",
        exchange="okx",
        base_currency="AAPL",
        quote_currency="USDT",
        trading_status="live",
        tick_size=D("0.01"),
        lot_size=lot_size,
        min_order_size=lot_size,
    )


def swap_instrument(*, max_lever: D = D("20")) -> Instrument:
    return Instrument(
        symbol="AAPL-USDT-SWAP",
        inst_type="SWAP",
        product_key="AAPL",
        asset_type="tokenized_equity",
        exchange="okx",
        base_currency="AAPL",
        quote_currency="USDT",
        trading_status="live",
        tick_size=D("0.01"),
        lot_size=D("0.01"),
        min_order_size=D("0.01"),
        ct_val=D("1"),
        ct_mult=D("1"),
        ct_type="linear",
        max_lever=max_lever,
    )


def spot_request(**overrides: object) -> TradeRequest:
    values: dict[str, object] = {
        "instance_id": "si_1",
        "inst_id": "XAAPL-USDT",
        "side": "buy",
        "order_type": "limit",
        "qty": D("10"),
        "price": D("100"),
        "ts": NOW,
    }
    values.update(overrides)
    return TradeRequest(**values)  # type: ignore[arg-type]


def swap_request(**overrides: object) -> TradeRequest:
    values: dict[str, object] = {
        "instance_id": "si_1",
        "inst_id": "AAPL-USDT-SWAP",
        "side": "buy",
        "order_type": "limit",
        "qty": D("1"),
        "price": D("100"),
        "leverage": D("3"),
        "funding_rate": D("0"),
        "liquidation_price": D("80"),
        "ts": NOW,
    }
    values.update(overrides)
    return TradeRequest(**values)  # type: ignore[arg-type]


def base_context(**overrides: object) -> RiskContext:
    values: dict[str, object] = {
        "equity": D("10000"),
        "available_balance": D("10000"),
    }
    values.update(overrides)
    return RiskContext(**values)  # type: ignore[arg-type]


def add_limits(**overrides: object) -> RiskLimits:
    return replace(RiskLimits(), **overrides)  # type: ignore[arg-type]


def rules_of(decision: object) -> set[str]:
    return {violation.rule for violation in decision.violations}  # type: ignore[attr-defined]


def test_positive_spot_signal_checks_every_applicable_rule() -> None:
    decision = evaluate(
        spot_request(), spot_instrument(), base_context(), RiskLimits(), halted=False
    )

    assert decision.allowed
    assert decision.violations == ()
    assert set(decision.checked_rules) == set(applicable_rule_names("SPOT"))
    assert "funding_rate" not in decision.checked_rules
    assert "liquidation_distance" not in decision.checked_rules
    assert "leverage" not in decision.checked_rules


def test_positive_swap_signal_checks_margin_and_funding_rules() -> None:
    decision = evaluate(
        swap_request(), swap_instrument(), base_context(), RiskLimits(), halted=False
    )

    assert decision.allowed
    assert decision.violations == ()
    assert set(decision.checked_rules) == set(applicable_rule_names("SWAP"))
    assert {"leverage", "funding_rate", "liquidation_distance"} <= set(decision.checked_rules)


def test_each_limit_has_a_triggering_case() -> None:
    cases: list[tuple[str, TradeRequest, Instrument, RiskContext, RiskLimits]] = [
        (
            "order_amount_ratio",
            spot_request(qty=D("30")),
            spot_instrument(),
            base_context(),
            RiskLimits(),
        ),
        (
            "instrument_weight",
            spot_request(qty=D("31")),
            spot_instrument(),
            base_context(),
            add_limits(max_order_ratio=D("1")),
        ),
        (
            "max_positions",
            spot_request(),
            spot_instrument(),
            base_context(
                positions=tuple(
                    PositionExposure(
                        instance_id="si_1",
                        inst_id=f"P{index}-USDT",
                        product_key=f"P{index}",
                        direction="long",
                        notional=D("10"),
                    )
                    for index in range(10)
                )
            ),
            RiskLimits(),
        ),
        (
            "duplicate_signal",
            spot_request(),
            spot_instrument(),
            base_context(
                recent_signals=(
                    SignalRecord(
                        instance_id="si_1",
                        inst_id="XAAPL-USDT",
                        side="buy",
                        at=NOW - timedelta(minutes=1),
                    ),
                )
            ),
            RiskLimits(),
        ),
        (
            "qty_precision",
            spot_request(qty=D("10.005")),
            spot_instrument(),
            base_context(),
            RiskLimits(),
        ),
        (
            "price_precision",
            spot_request(price=D("100.005")),
            spot_instrument(),
            base_context(),
            RiskLimits(),
        ),
        (
            "gross_exposure",
            spot_request(),
            spot_instrument(),
            base_context(
                positions=(PositionExposure("si_2", "MSFT-USDT", "MSFT", "long", D("19001")),)
            ),
            add_limits(
                max_instrument_weight=D("100"),
                max_abs_net_exposure=D("100"),
                max_concentration=D("100"),
            ),
        ),
        (
            "net_exposure",
            spot_request(),
            spot_instrument(),
            base_context(
                positions=(PositionExposure("si_2", "MSFT-USDT", "MSFT", "long", D("9500")),)
            ),
            add_limits(
                max_instrument_weight=D("100"),
                max_gross_exposure=D("100"),
                max_concentration=D("100"),
            ),
        ),
        (
            "concentration",
            spot_request(),
            spot_instrument(),
            base_context(
                positions=(PositionExposure("si_1", "XAAPL-USDT", "AAPL", "long", D("3500")),)
            ),
            add_limits(
                max_instrument_weight=D("100"),
                max_gross_exposure=D("100"),
                max_abs_net_exposure=D("100"),
            ),
        ),
        (
            "correlation_risk",
            spot_request(),
            spot_instrument(),
            base_context(
                positions=(PositionExposure("si_2", "MSFT-USDT", "MSFT", "long", D("5500")),),
                correlations=(Correlation("AAPL", "MSFT", D("0.9")),),
            ),
            add_limits(
                max_instrument_weight=D("100"),
                max_gross_exposure=D("100"),
                max_abs_net_exposure=D("100"),
                max_concentration=D("100"),
            ),
        ),
        (
            "multi_strategy_duplicate",
            spot_request(),
            spot_instrument(),
            base_context(
                positions=(
                    PositionExposure("si_2", "XAAPL-USDT", "AAPL", "long", D("100")),
                    PositionExposure("si_3", "XAAPL-USDT", "AAPL", "long", D("100")),
                )
            ),
            RiskLimits(),
        ),
        (
            "max_drawdown",
            spot_request(),
            spot_instrument(),
            base_context(drawdown=D("0.25")),
            RiskLimits(),
        ),
        (
            "available_balance",
            spot_request(),
            spot_instrument(),
            base_context(available_balance=D("500")),
            RiskLimits(),
        ),
        (
            "leverage",
            swap_request(leverage=D("11")),
            swap_instrument(),
            base_context(),
            RiskLimits(),
        ),
        (
            "funding_rate",
            swap_request(funding_rate=D("0.05")),
            swap_instrument(),
            base_context(),
            RiskLimits(),
        ),
        (
            "liquidation_distance",
            swap_request(liquidation_price=D("95")),
            swap_instrument(),
            base_context(),
            RiskLimits(),
        ),
    ]

    for rule, request, instrument, context, limits in cases:
        decision = evaluate(request, instrument, context, limits, halted=False)
        assert not decision.allowed, f"{rule} 没有拒绝"
        assert rule in rules_of(decision), f"{rule} 的触发结果里没有这条规则:{rules_of(decision)}"


def test_spot_skips_funding_and_liquidation_even_with_extreme_values() -> None:
    request = spot_request(funding_rate=D("5"), liquidation_price=D("99.99"))

    decision = evaluate(request, spot_instrument(), base_context(), RiskLimits(), halted=False)

    assert decision.allowed
    assert "funding_rate" not in decision.checked_rules
    assert "liquidation_distance" not in decision.checked_rules
    assert "funding_rate" not in rules_of(decision)
    assert "liquidation_distance" not in rules_of(decision)


def test_same_extreme_values_are_checked_and_rejected_for_swap() -> None:
    request = swap_request(funding_rate=D("5"), liquidation_price=D("99.99"))

    decision = evaluate(request, swap_instrument(), base_context(), RiskLimits(), halted=False)

    assert not decision.allowed
    assert {"funding_rate", "liquidation_distance"} <= set(decision.checked_rules)
    assert {"funding_rate", "liquidation_distance"} <= rules_of(decision)


def test_rule_applicability_never_returns_an_empty_set() -> None:
    applicability = dict(rule_applicability())

    assert applicability
    for rule, categories in applicability.items():
        assert categories, f"{rule} 没有适用类别"

    assert set(applicability["available_balance"]) == {"SPOT"}
    assert set(applicability["leverage"]) == {"SWAP"}
    assert set(applicability["funding_rate"]) == {"SWAP"}
    assert set(applicability["liquidation_distance"]) == {"SWAP"}
    assert set(applicability["order_amount_ratio"]) == {"SPOT", "SWAP"}


def test_emergency_stop_blocks_new_positions_but_not_reduce_only() -> None:
    blocked = evaluate(spot_request(), spot_instrument(), base_context(), RiskLimits(), halted=True)
    reduced = evaluate(
        spot_request(side="sell", reduce_only=True),
        spot_instrument(),
        base_context(),
        RiskLimits(),
        halted=True,
    )

    assert not blocked.allowed
    assert "emergency_stop" in rules_of(blocked)
    assert reduced.allowed
    assert reduced.violations == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("instance_id", " "),
        ("inst_id", " "),
        ("side", "hold"),
        ("order_type", "stop"),
        ("qty", D("0")),
    ],
)
def test_invalid_order_request_is_rejected(field: str, value: object) -> None:
    from app.core import ValidationError

    with pytest.raises(ValidationError):
        spot_request(**{field: value})


def test_market_order_uses_mark_price_for_notional() -> None:
    decision = evaluate(
        spot_request(order_type="market", price=None, mark_price=D("100")),
        spot_instrument(),
        base_context(),
        RiskLimits(),
        halted=False,
    )

    assert decision.allowed
    assert "price_precision" in decision.checked_rules


def test_strategy_level_weight_uses_the_strategy_budget_and_its_own_positions() -> None:
    """策略级单标的权重只看本策略：别的策略持有同一产品不算进来。"""

    limits = add_limits(max_order_ratio=D("1"), max_instrument_weight=D("0.30"))
    own = evaluate(
        spot_request(qty=D("4")),
        spot_instrument(),
        base_context(
            strategy_equity=D("1000"),
            positions=(PositionExposure("si_2", "XAAPL-USDT", "AAPL", "long", D("5000")),),
        ),
        limits,
        halted=False,
    )
    other_only = evaluate(
        spot_request(qty=D("1")),
        spot_instrument(),
        base_context(
            strategy_equity=D("1000"),
            positions=(PositionExposure("si_2", "XAAPL-USDT", "AAPL", "long", D("5000")),),
        ),
        limits,
        halted=False,
    )

    assert "instrument_weight" in rules_of(own)
    assert "instrument_weight" not in rules_of(other_only)


def test_zero_strategy_budget_rejects_instead_of_falling_back_to_portfolio_equity() -> None:
    """预算为 0 是一个真实预算, 不能当成「没有预算」改用组合权益。"""

    decision = evaluate(
        spot_request(qty=D("1")),
        spot_instrument(),
        base_context(strategy_equity=D("0")),
        RiskLimits(),
        halted=False,
    )

    assert not decision.allowed
    assert {"order_amount_ratio", "instrument_weight"} <= rules_of(decision)


def test_swap_rejects_missing_funding_and_liquidation_inputs() -> None:
    """保证金类别缺少资金费率或强平价时不能当成「等于 0」放过。"""

    decision = evaluate(
        swap_request(funding_rate=None, liquidation_price=None),
        swap_instrument(),
        base_context(),
        RiskLimits(),
        halted=False,
    )

    assert {"funding_rate", "liquidation_distance"} <= rules_of(decision)

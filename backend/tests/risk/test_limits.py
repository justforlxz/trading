"""策略级限额纯函数用例（P2-02）。

判定语义：严格超过阈值才拒绝；等于阈值或差值在 1e-9 容差内放行。
"""

from decimal import Decimal

from app.risk.core.limits import Breach, LegIntent, Limits, evaluate_limits

CAPITAL = Decimal("100000")


def _limits(**overrides: str) -> Limits:
    values = {
        "max_order_notional": Decimal("100000"),
        "max_leg_weight": Decimal("0.6"),
        "max_leverage": Decimal("1.0"),
        "max_gross_exposure": Decimal("1.0"),
        "max_net_exposure": Decimal("1.0"),
        "max_instrument_weight": Decimal("0.6"),
        "max_concentration": Decimal("0.5"),
    }
    values.update({key: Decimal(value) for key, value in overrides.items()})
    return Limits(**values)


def _long(weight: str, *, instrument_id: int = 1) -> LegIntent:
    return LegIntent(
        instrument_id=instrument_id,
        side="long",
        weight=Decimal(weight),
        notional=CAPITAL * Decimal(weight),
    )


def _short(weight: str, *, instrument_id: int = 2) -> LegIntent:
    return LegIntent(
        instrument_id=instrument_id,
        side="short",
        weight=Decimal(weight),
        notional=CAPITAL * Decimal(weight),
    )


def _codes(verdict) -> set[str]:
    return {breach.code for breach in verdict.breaches}


def test_balanced_portfolio_passes_and_metrics_match() -> None:
    verdict = evaluate_limits(
        legs=(_long("0.45"), _short("0.35")), limits=_limits(), capital=CAPITAL
    )
    assert verdict.ok is True
    assert verdict.breaches == ()
    assert verdict.gross_exposure == Decimal("80000")
    assert verdict.net_exposure == Decimal("10000")
    assert verdict.leverage == Decimal("0.8")


def test_equal_to_threshold_passes() -> None:
    verdict = evaluate_limits(
        legs=(_long("0.6"),),
        limits=_limits(max_instrument_weight="0.6", max_concentration="0.6"),
        capital=CAPITAL,
    )
    assert verdict.ok is True
    assert verdict.breaches == ()


def test_within_tolerance_passes() -> None:
    verdict = evaluate_limits(
        legs=(_long("0.6000000005"),),
        limits=_limits(max_instrument_weight="0.7", max_concentration="0.7"),
        capital=CAPITAL,
    )
    assert verdict.ok is True
    assert verdict.breaches == ()


def test_exceeding_by_two_nanounits_rejected() -> None:
    verdict = evaluate_limits(
        legs=(_long("0.600000002"),),
        limits=_limits(max_instrument_weight="0.9", max_concentration="0.9"),
        capital=CAPITAL,
    )
    assert verdict.ok is False
    assert "leg_weight_exceeded" in _codes(verdict)
    breach = next(item for item in verdict.breaches if item.code == "leg_weight_exceeded")
    assert breach.observed == Decimal("0.600000002")
    assert breach.threshold == Decimal("0.6")


def test_order_notional_breach() -> None:
    verdict = evaluate_limits(
        legs=(_long("0.6"),),
        limits=_limits(max_order_notional="59999.99", max_concentration="0.9"),
        capital=CAPITAL,
    )
    assert verdict.ok is False
    assert "order_notional_exceeded" in _codes(verdict)


def test_gross_and_leverage_breach() -> None:
    verdict = evaluate_limits(
        legs=(_long("0.7", instrument_id=1), _short("0.4", instrument_id=2)),
        limits=_limits(
            max_leverage="1.0",
            max_gross_exposure="1.0",
            max_leg_weight="1.0",
            max_instrument_weight="1.0",
            max_concentration="1.0",
        ),
        capital=CAPITAL,
    )
    assert verdict.ok is False
    assert {"gross_exposure_exceeded", "leverage_exceeded"} <= _codes(verdict)
    assert verdict.leverage == Decimal("1.1")


def test_net_exposure_breach() -> None:
    verdict = evaluate_limits(
        legs=(_long("0.9", instrument_id=1),),
        limits=_limits(
            max_net_exposure="0.5",
            max_gross_exposure="2.0",
            max_leverage="2.0",
            max_leg_weight="1.0",
            max_instrument_weight="1.0",
            max_concentration="1.0",
        ),
        capital=CAPITAL,
    )
    assert verdict.ok is False
    assert _codes(verdict) == {"net_exposure_exceeded"}


def test_concentration_breach_on_single_instrument() -> None:
    verdict = evaluate_limits(
        legs=(_long("0.55"),),
        limits=_limits(max_instrument_weight="0.9", max_concentration="0.5"),
        capital=CAPITAL,
    )
    assert verdict.ok is False
    assert _codes(verdict) == {"concentration_exceeded"}
    assert verdict.breaches[0].field == "instrument:1"


def test_empty_portfolio_rejected() -> None:
    verdict = evaluate_limits(legs=(), limits=_limits(), capital=CAPITAL)
    assert verdict.ok is False
    assert _codes(verdict) == {"risk_empty_portfolio"}


def test_non_positive_capital_rejected() -> None:
    verdict = evaluate_limits(legs=(_long("0.1"),), limits=_limits(), capital=Decimal("0"))
    assert verdict.ok is False
    assert _codes(verdict) == {"risk_insufficient_capital"}


def test_invalid_side_rejected() -> None:
    verdict = evaluate_limits(
        legs=(
            LegIntent(instrument_id=1, side="flat", weight=Decimal("0.1"), notional=Decimal("1")),
        ),
        limits=_limits(),
        capital=CAPITAL,
    )
    assert verdict.ok is False
    assert _codes(verdict) == {"risk_invalid_side"}


def test_signed_weights_are_valid_for_relative_value() -> None:
    """空头腿用负权重表达方向: 限额按绝对值校验, 净敞口按 side 抵消。"""

    verdict = evaluate_limits(
        legs=(
            _long("0.3"),
            LegIntent(
                instrument_id=2,
                side="short",
                weight=Decimal("-0.3"),
                notional=Decimal("-30000"),
            ),
        ),
        limits=_limits(),
        capital=CAPITAL,
    )
    assert verdict.ok is True, verdict.breaches
    assert verdict.gross_exposure == Decimal("60000")
    assert verdict.net_exposure == Decimal("0")


def test_deterministic_for_same_input() -> None:
    legs = (_long("0.6"), _short("0.4"))
    first = evaluate_limits(legs=legs, limits=_limits(), capital=CAPITAL)
    second = evaluate_limits(legs=legs, limits=_limits(), capital=CAPITAL)
    assert first == second
    assert isinstance(first.breaches, tuple)


def test_breach_is_decimal_not_float() -> None:
    verdict = evaluate_limits(legs=(_long("0.7"),), limits=_limits(), capital=CAPITAL)
    assert all(isinstance(item, Breach) for item in verdict.breaches)
    assert all(isinstance(item.observed, Decimal) for item in verdict.breaches)

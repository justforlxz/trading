"""风险与敞口的纯计算用例：固定输入下手算每一步。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.risk import (
    RULE_HIGH_LEVERAGE,
    RULE_MARGIN_USAGE,
    RULE_SINGLE_INSTRUMENT_WEIGHT,
    RULE_STOP_DISTANCE,
    RULE_STOP_MISSING,
    PositionRiskInput,
    RiskThresholds,
    build_exposure,
    notional_value,
)

D = Decimal
NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
THRESHOLDS = RiskThresholds(
    max_leverage=D("3"),
    max_single_instrument_weight_pct=D("80"),
    max_margin_usage_pct=D("70"),
)


def _position(
    ref: str,
    *,
    source: str = "exchange",
    symbol: str = "AAPL-USDT-SWAP",
    display: str = "AAPL-USDT",
    side: str = "long",
    size: str = "8",
    mark: str | None = "231.42",
    stop: str | None = "210",
    atr: str | None = "2",
    lever: str | None = "3",
    sector: str | None = "semiconductor",
    inst_type: str | None = "SWAP",
    ct_val: str | None = "1",
    ct_mult: str | None = "1",
) -> PositionRiskInput:
    return PositionRiskInput(
        position_ref=ref,
        source=source,  # type: ignore[arg-type]
        inst_id=symbol,
        display_symbol=display,
        side=side,  # type: ignore[arg-type]
        size=D(size),
        inst_type=inst_type,
        mark_px=None if mark is None else D(mark),
        stop_px=None if stop is None else D(stop),
        atr=None if atr is None else D(atr),
        lever=None if lever is None else D(lever),
        sector=sector,
        ct_val=None if ct_val is None else D(ct_val),
        ct_mult=None if ct_mult is None else D(ct_mult),
    )


def _report(
    *positions: PositionRiskInput,
    thresholds: RiskThresholds = THRESHOLDS,
    **kwargs: object,
):
    return build_exposure(
        positions,
        as_of=NOW,
        currency="USDT",
        thresholds=thresholds,
        **kwargs,
    )


NO_CONCENTRATION_RULE = RiskThresholds(
    max_leverage=D("3"),
    max_single_instrument_weight_pct=D("100"),
    max_margin_usage_pct=D("70"),
)


def test_mixed_long_short_notional_weights_sectors_and_distances() -> None:
    long = _position("exchange:okx-main:1")
    short = _position(
        "exchange:okx-main:2",
        symbol="TSLA-USDT-SWAP",
        display="TSLA-USDT",
        side="short",
        size="10",
        mark="98.04",
        stop="110",
        sector="auto",
    )

    report = _report(long, short, margin_usage_pct=D("45.36"), margin_usage_basis="margin_ratio")

    summary = report.summary
    assert summary.long_notional == D("1851.36")
    assert summary.short_notional == D("980.40")
    assert summary.net_notional == D("870.96")
    assert summary.gross_notional == D("2831.76")
    assert summary.margin_usage_pct == D("45.36")
    assert summary.margin_usage_basis == "margin_ratio"
    assert summary.risk_level == "low"
    assert report.status == "ok"

    long_view, short_view = report.positions
    assert long_view.weight_pct == D("1851.36") / D("2831.76") * D(100)
    assert long_view.stop_distance_pct == (D("231.42") - D("210")) / D("231.42") * D(100)
    assert long_view.atr_distance == (D("231.42") - D("210")) / D("2")
    assert short_view.weight_pct == D("980.40") / D("2831.76") * D(100)
    assert short_view.stop_distance_pct == (D("110") - D("98.04")) / D("98.04") * D(100)
    assert short_view.atr_distance == (D("110") - D("98.04")) / D("2")
    assert report.rules == ()

    assert {(item.sector, item.notional) for item in report.sectors} == {
        ("auto", D("980.40")),
        ("semiconductor", D("1851.36")),
    }


def test_manual_quantity_is_base_units_not_contract_count() -> None:
    manual = _position("manual:1", source="manual", size="2", mark="100", stop="90", ct_val="0.01")
    exchange = _position("exchange:okx-main:1", size="2", mark="100", stop="90", ct_val="0.01")

    assert notional_value(manual) == D("200")
    assert notional_value(exchange) == D("2")


def test_short_stop_that_price_has_crossed_is_critical() -> None:
    report = _report(
        _position("manual:1", side="short", mark="100", stop="95", atr="2"),
    )

    item = report.positions[0]
    assert item.stop_distance_pct == D("-5")
    assert item.atr_distance == D("-2.5")
    rule = next(rule for rule in report.rules if rule.rule_id == RULE_STOP_DISTANCE)
    assert rule.level == "critical"
    assert rule.value == D("-2.5")
    assert rule.threshold == D("1")
    assert report.summary.risk_level == "high"


def test_stop_closer_than_one_atr_is_warning() -> None:
    report = _report(_position("exchange:okx-main:1", mark="100", stop="99", atr="2"))

    rule = next(rule for rule in report.rules if rule.rule_id == RULE_STOP_DISTANCE)
    assert rule.level == "warning"
    assert rule.value == D("0.5")
    assert rule.threshold == D("1")
    assert report.summary.risk_level == "medium"
    assert "stop_distance" in report.positions[0].flags


def test_missing_stop_is_reported_without_inventing_a_distance() -> None:
    report = _report(_position("manual:1", stop=None), thresholds=NO_CONCENTRATION_RULE)

    item = report.positions[0]
    assert item.stop_px is None
    assert item.stop_distance_pct is None
    assert item.atr_distance is None
    assert item.flags == ("stop_missing",)
    rule = next(rule for rule in report.rules if rule.rule_id == RULE_STOP_MISSING)
    assert rule.value is None
    assert rule.threshold is None
    assert rule.level == "warning"


def test_missing_atr_leaves_atr_distance_empty_and_marks_the_gap() -> None:
    report = _report(_position("manual:1", atr=None), thresholds=NO_CONCENTRATION_RULE)

    item = report.positions[0]
    assert item.stop_distance_pct is not None
    assert item.atr_distance is None
    assert item.flags == ("atr_unavailable",)
    assert all(rule.rule_id != RULE_STOP_DISTANCE for rule in report.rules)


def test_missing_market_data_keeps_the_position_but_not_a_fake_notional() -> None:
    report = _report(_position("manual:1", mark=None))

    item = report.positions[0]
    assert item.notional is None
    assert item.weight_pct is None
    assert item.stop_distance_pct is None
    assert item.atr_distance is None
    assert item.flags == ("no_market_data",)
    assert report.summary.gross_notional == D("0")
    assert report.sectors == ()


def test_high_leverage_uses_the_configured_threshold() -> None:
    report = _report(_position("manual:1", lever="4"))

    rule = next(rule for rule in report.rules if rule.rule_id == RULE_HIGH_LEVERAGE)
    assert rule.value == D("4")
    assert rule.threshold == D("3")
    assert rule.level == "warning"


def test_single_instrument_weight_aggregates_spot_and_swap_of_the_same_product() -> None:
    spot = _position(
        "exchange:okx-main:spot",
        symbol="XAAPL-USDT",
        inst_type="SPOT",
        size="10",
        mark="10",
        ct_val=None,
        ct_mult=None,
    )
    swap = _position(
        "exchange:okx-main:swap",
        symbol="AAPL-USDT-SWAP",
        size="10",
        mark="10",
    )
    other = _position(
        "exchange:okx-main:other",
        symbol="MSFT-USDT-SWAP",
        display="MSFT-USDT",
        size="4",
        mark="10",
    )

    report = _report(
        spot,
        swap,
        other,
        thresholds=RiskThresholds(
            max_leverage=D("3"),
            max_single_instrument_weight_pct=D("80"),
            max_margin_usage_pct=D("70"),
        ),
    )

    rule = next(rule for rule in report.rules if rule.rule_id == RULE_SINGLE_INSTRUMENT_WEIGHT)
    assert rule.value == D("200") / D("240") * D(100)
    assert rule.threshold == D("80")
    assert rule.position_ref == "exchange:okx-main:spot"
    assert "single_instrument_weight" in report.positions[0].flags
    assert "single_instrument_weight" in report.positions[1].flags
    assert "single_instrument_weight" not in report.positions[2].flags


def test_margin_usage_over_threshold_is_a_rule() -> None:
    report = _report(
        _position("manual:1"),
        margin_usage_pct=D("75"),
        margin_usage_basis="used_margin",
    )

    rule = next(rule for rule in report.rules if rule.rule_id == RULE_MARGIN_USAGE)
    assert rule.position_ref is None
    assert rule.value == D("75")
    assert rule.threshold == D("70")
    assert report.summary.risk_level == "medium"


def test_empty_portfolio_is_zero_exposure_and_low_risk() -> None:
    report = _report()

    assert report.status == "empty"
    assert report.summary.gross_notional == D("0")
    assert report.summary.risk_level == "low"
    assert report.positions == ()
    assert report.sectors == ()
    assert report.rules == ()


@pytest.mark.parametrize(
    ("position", "expected"),
    [
        (_position("x", inst_type="SPOT", size="10", mark="12.5"), D("125")),
        (_position("x", size="3", mark="100", ct_val="2", ct_mult="5"), D("3000")),
        (_position("x", ct_val=None), None),
        (_position("x", inst_type=None), None),
    ],
)
def test_notional_follows_contract_specification(
    position: PositionRiskInput, expected: Decimal | None
) -> None:
    assert notional_value(position) == expected

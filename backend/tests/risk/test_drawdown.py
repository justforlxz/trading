"""最大回撤监控纯函数用例（P2-05）：三级阈值与四取值动作。"""

from decimal import Decimal

import pytest

from app.risk.core.drawdown import (
    ACTIONS,
    DrawdownThresholds,
    drawdown_series,
    evaluate_drawdown,
    validate_thresholds,
)
from app.risk.errors import RiskError

THRESHOLDS = DrawdownThresholds(warn=Decimal("0.05"), reduce=Decimal("0.10"), close=Decimal("0.20"))
PEAK = Decimal("100000")


def test_threshold_validation_accepts_monotonic_series() -> None:
    validate_thresholds(THRESHOLDS)


@pytest.mark.parametrize(
    "warn,reduce,close",
    [
        ("0.10", "0.05", "0.20"),
        ("0", "0.10", "0.20"),
        ("0.05", "0.10", "0.10"),
    ],
)
def test_threshold_validation_rejects_invalid(warn: str, reduce: str, close: str) -> None:
    with pytest.raises(RiskError) as excinfo:
        validate_thresholds(
            DrawdownThresholds(warn=Decimal(warn), reduce=Decimal(reduce), close=Decimal(close))
        )
    assert excinfo.value.code == "risk_invalid_threshold"


def test_no_breach_below_warn() -> None:
    verdict = evaluate_drawdown(equity=Decimal("96000"), peak=PEAK, thresholds=THRESHOLDS)
    assert verdict.drawdown == Decimal("0.04")
    assert verdict.action == "none"
    assert verdict.severity is None
    assert verdict.breached is False


def test_warn_level_triggers() -> None:
    verdict = evaluate_drawdown(equity=Decimal("95000"), peak=PEAK, thresholds=THRESHOLDS)
    assert verdict.action == "warn"
    assert verdict.severity == "tier1"
    assert verdict.breached is True


def test_reduce_level_triggers() -> None:
    verdict = evaluate_drawdown(equity=Decimal("90000"), peak=PEAK, thresholds=THRESHOLDS)
    assert verdict.action == "reduce"
    assert verdict.severity == "tier2"


def test_close_level_triggers() -> None:
    verdict = evaluate_drawdown(equity=Decimal("80000"), peak=PEAK, thresholds=THRESHOLDS)
    assert verdict.action == "close"
    assert verdict.severity == "tier3"


def test_action_is_always_one_of_four_values() -> None:
    for equity in ("100000", "95000", "90000", "80000"):
        verdict = evaluate_drawdown(equity=Decimal(equity), peak=PEAK, thresholds=THRESHOLDS)
        assert verdict.action in ACTIONS


def test_invalid_inputs_raise() -> None:
    with pytest.raises(RiskError) as zero_peak:
        evaluate_drawdown(equity=Decimal("1"), peak=Decimal("0"), thresholds=THRESHOLDS)
    assert zero_peak.value.code == "risk_invalid_input"
    with pytest.raises(RiskError) as negative_equity:
        evaluate_drawdown(equity=Decimal("-1"), peak=PEAK, thresholds=THRESHOLDS)
    assert negative_equity.value.code == "risk_invalid_input"


def test_series_peak_and_max_drawdown_match_hand_computation() -> None:
    peak, max_drawdown = drawdown_series(
        (Decimal("100"), Decimal("120"), Decimal("90"), Decimal("110"))
    )
    assert peak == Decimal("120")
    assert max_drawdown == Decimal("0.25")


def test_deterministic_field_by_field() -> None:
    first = evaluate_drawdown(equity=Decimal("90000"), peak=PEAK, thresholds=THRESHOLDS)
    second = evaluate_drawdown(equity=Decimal("90000"), peak=PEAK, thresholds=THRESHOLDS)
    assert first == second
    assert (first.drawdown, first.action, first.severity, first.breached) == (
        second.drawdown,
        second.action,
        second.severity,
        second.breached,
    )

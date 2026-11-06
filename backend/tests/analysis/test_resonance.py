"""共振与相关性突变纯函数单测（P1-12）：强度单调、突变可复现。"""

import random

import pytest

from app.analysis.core import resonance as core


def test_resonance_strength_rises_with_same_direction_share() -> None:
    """注入 30% / 60% / 90% 同向涨幅，强度必须依次不减且至少一步严格增加。"""

    def _series(up: int, down: int) -> list[float]:
        return [0.01] * up + [-0.01] * down

    first = core.resonance(_series(6, 4))
    second = core.resonance(_series(7, 3))
    third = core.resonance(_series(9, 1))

    assert first.direction == second.direction == third.direction == "long"
    assert first.strength is not None
    assert second.strength is not None
    assert third.strength is not None
    assert first.strength <= second.strength <= third.strength
    assert first.strength < third.strength
    assert first.strength == pytest.approx(0.6)
    assert third.strength == pytest.approx(0.9)


def test_resonance_picks_the_dominant_direction() -> None:
    conclusion = core.resonance([0.01] * 3 + [-0.01] * 7)
    assert conclusion.direction == "short"
    assert conclusion.strength == pytest.approx(0.7)


def test_breadth_ignores_non_finite_values_and_counts_flat() -> None:
    counts = core.breadth([0.01, -0.01, 0.0, float("nan"), float("inf")])
    assert counts == core.Breadth(up=1, down=1, flat=1, total=3)
    assert counts.up_ratio == pytest.approx(1 / 3)


def test_empty_cross_section_has_no_direction() -> None:
    conclusion = core.resonance([])
    assert conclusion.defined is False
    assert conclusion.direction is None
    assert conclusion.strength is None


def test_anomaly_is_flagged_when_uncorrelated_assets_suddenly_move_together() -> None:
    rng = random.Random(11)
    left = [rng.gauss(0.0, 1.0) for _ in range(80)]
    right = [rng.gauss(0.0, 1.0) for _ in range(60)] + [
        value + rng.gauss(0.0, 0.05) for value in left[-20:]
    ]

    shift = core.correlation_shift(left, right, window=20)

    assert shift.defined is True
    assert shift.flagged is True
    assert shift.window == 20
    assert shift.recent is not None and shift.recent > 0.9
    assert shift.baseline is not None and abs(shift.baseline) < 0.5
    assert shift.delta is not None and shift.delta > 0.4


def test_control_series_is_not_flagged() -> None:
    rng = random.Random(12)
    left = [rng.gauss(0.0, 1.0) for _ in range(80)]
    right = [rng.gauss(0.0, 1.0) for _ in range(80)]

    shift = core.correlation_shift(left, right, window=20)

    assert shift.defined is True
    assert shift.flagged is False


def test_shift_is_undefined_without_enough_samples() -> None:
    shift = core.correlation_shift([0.1] * 10, [0.2] * 10, window=20)
    assert shift.defined is False
    assert shift.flagged is False

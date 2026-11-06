"""相对强弱纯函数单测（AC5）：手算对拍、窗口不足与非法输入。"""

import pytest

from app.analysis.core import relative_strength as rs

TOLERANCE = 1e-12


def test_ratio_series_is_normalized_to_one() -> None:
    ratios = rs.ratio_series([10.0, 12.0, 15.0], [5.0, 5.0, 6.0])
    assert ratios is not None
    assert ratios == pytest.approx([1.0, 1.2, 1.25], abs=TOLERANCE)


def test_ratio_series_rejects_bad_input() -> None:
    assert rs.ratio_series([1.0], [1.0]) is None
    assert rs.ratio_series([1.0, 2.0], [1.0]) is None
    assert rs.ratio_series([1.0, 0.0], [1.0, 2.0]) is None


def test_compute_matches_hand_calculation() -> None:
    result = rs.compute([10.0, 12.0, 15.0], [5.0, 5.0, 6.0], momentum_bars=1)
    assert result.defined is True
    assert result.reason is None
    assert result.rs_ratio == pytest.approx(1.25, abs=TOLERANCE)
    assert result.rs_momentum == pytest.approx(1.25 / 1.2 - 1.0, abs=TOLERANCE)
    assert result.target_return == pytest.approx(0.5, abs=TOLERANCE)
    assert result.counterparty_return == pytest.approx(0.2, abs=TOLERANCE)
    assert result.excess_return == pytest.approx(0.3, abs=TOLERANCE)
    assert result.trend == rs.TREND_RISING
    assert result.momentum_reason is None


def test_compute_falling_and_flat_trends() -> None:
    falling = rs.compute([10.0, 9.0, 8.0], [5.0, 5.0, 5.0], momentum_bars=1)
    assert falling.trend == rs.TREND_FALLING
    flat = rs.compute([10.0, 10.0, 10.0], [5.0, 5.0, 5.0], momentum_bars=1)
    assert flat.trend == rs.TREND_FLAT


def test_compute_momentum_window_too_short_keeps_ratio() -> None:
    result = rs.compute([10.0, 12.0], [5.0, 5.0], momentum_bars=3)
    assert result.defined is True
    assert result.rs_ratio == pytest.approx(1.2, abs=TOLERANCE)
    assert result.rs_momentum is None
    assert result.momentum_reason == rs.REASON_INSUFFICIENT
    assert result.trend is None


def test_compute_insufficient_window_has_reason() -> None:
    result = rs.compute([10.0], [5.0], momentum_bars=1)
    assert result.defined is False
    assert result.reason == rs.REASON_INSUFFICIENT
    assert result.rs_ratio is None


def test_compute_length_mismatch_has_reason() -> None:
    result = rs.compute([10.0, 11.0], [5.0], momentum_bars=1)
    assert result.defined is False
    assert result.reason == rs.REASON_LENGTH_MISMATCH


def test_compute_non_positive_price_has_reason() -> None:
    result = rs.compute([10.0, -1.0], [5.0, 5.0], momentum_bars=1)
    assert result.defined is False
    assert result.reason == rs.REASON_NON_POSITIVE


def test_compute_rejects_non_positive_momentum_window() -> None:
    with pytest.raises(ValueError):
        rs.compute([1.0, 2.0], [1.0, 2.0], momentum_bars=0)


def test_compute_is_deterministic() -> None:
    first = rs.compute([10.0, 11.5, 13.0], [5.0, 5.2, 5.5], momentum_bars=1)
    second = rs.compute([10.0, 11.5, 13.0], [5.0, 5.2, 5.5], momentum_bars=1)
    assert first == second

"""滚动相关性与两标的相对强弱（已知答案用例，不连库）。

期望值来自独立实现或解析解：

- 整段窗口的相关系数与标准库 `statistics.correlation` 对拍；
- 线性同向 / 严格反向的构造序列解析解为 `±1`；
- 相对强弱是逐点相除，期望值直接手算。

时间戳统一带时区：`open_time` 必须带时区，naive 时间会被判为调用方错误。
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta

import pytest

from app.core import ValidationError
from app.market import MIN_SAMPLES, relative_strength_ratio, rolling_correlation

START = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
TOL = 1e-12


def _series(values: list[float], *, start: datetime = START) -> list[tuple[datetime, float]]:
    """从 `start` 起每小时一个观测点。"""

    return [(start + timedelta(hours=index), value) for index, value in enumerate(values)]


# ------------------------------------------------------------ rolling correlation


def test_full_window_matches_standard_library() -> None:
    """整段窗口的系数与独立实现（`statistics.correlation`）一致。"""

    xs = [3.0, 1.0, 4.0, 1.5, 5.0, 9.0, 2.5]
    ys = [2.0, 7.0, 1.0, 8.0, 2.0, 8.0, 4.5]

    moment, coefficient = rolling_correlation(_series(xs), _series(ys), window=len(xs))[-1]

    # 系数挂在窗口末端的那个时刻上。
    assert moment == START + timedelta(hours=len(xs) - 1)
    assert coefficient is not None
    assert coefficient == pytest.approx(statistics.correlation(xs, ys), abs=TOL)


def test_last_window_uses_only_the_most_recent_samples() -> None:
    """滑动窗口只看最近 `window` 个样本：与手算的末三条一致。"""

    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [5.0, 3.0, 4.0, 9.0, 10.0]

    result = rolling_correlation(_series(xs), _series(ys), window=3)

    assert result[3] == (
        START + timedelta(hours=3),
        pytest.approx(statistics.correlation(xs[1:4], ys[1:4]), abs=TOL),
    )
    assert result[4] == (
        START + timedelta(hours=4),
        pytest.approx(statistics.correlation(xs[2:5], ys[2:5]), abs=TOL),
    )


def test_codirectional_series_is_one() -> None:
    """完全同向（线性递增的两条序列）系数为 1.0。"""

    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [10.0, 20.0, 30.0, 40.0, 50.0]

    _, coefficient = rolling_correlation(_series(xs), _series(ys), window=5)[-1]

    assert coefficient is not None
    assert abs(coefficient - 1.0) <= 1e-9


def test_inverse_series_is_minus_one() -> None:
    """完全反向系数为 -1.0。"""

    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [50.0, 40.0, 30.0, 20.0, 10.0]

    _, coefficient = rolling_correlation(_series(xs), _series(ys), window=5)[-1]

    assert coefficient is not None
    assert abs(coefficient + 1.0) <= 1e-9


def test_warmup_positions_are_undefined_without_interpolation() -> None:
    """窗口未满的时间点系数为 `None`，输出与交集序列逐个对应。"""

    result = rolling_correlation(_series([1.0, 2.0, 4.0, 8.0]), _series([2.0, 3.0, 5.0, 9.0]), 3)

    assert [moment for moment, _ in result] == [
        START + timedelta(hours=index) for index in range(4)
    ]
    assert [coefficient is None for _, coefficient in result] == [True, True, False, False]


def test_window_below_min_samples_is_undefined_everywhere() -> None:
    """样本数小于 `MIN_SAMPLES` 时不硬凑系数：`window` 为 1 或 2 全部为 `None`。"""

    series_a = _series([1.0, 2.0, 3.0, 4.0])
    series_b = _series([2.0, 4.0, 6.0, 8.0])

    for window in range(1, MIN_SAMPLES):
        assert all(
            coefficient is None
            for _, coefficient in rolling_correlation(series_a, series_b, window=window)
        )


def test_constant_window_is_undefined() -> None:
    """窗口内某一侧方差为 0 时系数未定义，不返回 0、也不插值。"""

    series_a = _series([1.0, 2.0, 3.0, 4.0])
    series_b = _series([7.0, 7.0, 7.0, 7.0])

    _, coefficient = rolling_correlation(series_a, series_b, window=4)[-1]

    assert coefficient is None


def test_alignment_keeps_only_common_timestamps() -> None:
    """两条序列只有共同的 `open_time` 参与计算，缺的那一侧不补。"""

    series_a = _series([1.0, 2.0, 3.0, 4.0])
    series_b = _series([2.0, 4.0, 6.0, 8.0], start=START + timedelta(hours=1))

    result = rolling_correlation(series_a, series_b, window=3)

    assert [moment for moment, _ in result] == [
        START + timedelta(hours=index) for index in (1, 2, 3)
    ]
    assert result[0][1] is None
    assert result[-1][1] is not None


def test_window_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        rolling_correlation(_series([1.0]), _series([1.0]), window=0)


def test_naive_timestamp_is_rejected() -> None:
    naive = [(datetime(2026, 11, 6, 0, 0), 1.0)]

    with pytest.raises(ValidationError):
        rolling_correlation(naive, naive, window=1)


# ------------------------------------------------------------- relative strength


def test_relative_strength_is_the_hand_computed_ratio() -> None:
    """相对强弱是逐点相除：2/1、3/2、4/8 → 2.0、1.5、0.5。"""

    series_a = _series([2.0, 3.0, 4.0])
    series_b = _series([1.0, 2.0, 8.0])

    result = relative_strength_ratio(series_a, series_b)

    assert [moment for moment, _ in result] == [
        START + timedelta(hours=index) for index in range(3)
    ]
    assert [ratio for _, ratio in result] == [
        pytest.approx(2.0, abs=1e-9),
        pytest.approx(1.5, abs=1e-9),
        pytest.approx(0.5, abs=1e-9),
    ]


def test_relative_strength_with_zero_denominator_is_undefined() -> None:
    """分母为 0 时记 `None`，不折成一个很大的数。"""

    result = relative_strength_ratio(_series([2.0, 3.0]), _series([1.0, 0.0]))

    assert result[0][1] == pytest.approx(2.0, abs=1e-9)
    assert result[1][1] is None


def test_relative_strength_aligns_on_common_timestamps() -> None:
    result = relative_strength_ratio(
        _series([2.0, 3.0, 4.0]), _series([1.0, 2.0], start=START + timedelta(hours=2))
    )

    assert [moment for moment, _ in result] == [START + timedelta(hours=2)]

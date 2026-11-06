"""相关性引擎单测（AC3）：与 numpy/scipy 对拍、端点值、未定义与确定性。"""

import math
import random

import numpy as np
import pytest
from scipy import stats

from app.analysis.core import correlation

TOLERANCE = 1e-12


def _wave(n: int = 160, *, seed: int = 11, noise: float = 0.3) -> tuple[list[float], list[float]]:
    """有确定性随机扰动的趋势序列：`y` 与 `x` 正相关但不是线性复刻。"""

    rng = random.Random(seed)
    xs = [math.sin(index / 7.0) * 3.0 + rng.gauss(0.0, noise) for index in range(n)]
    ys = [0.8 * value + rng.gauss(0.0, noise) for value in xs]
    return xs, ys


def test_pearson_matches_numpy() -> None:
    xs, ys = _wave()
    expected = float(np.corrcoef(xs, ys)[0, 1])
    assert correlation.pearson(xs, ys) == pytest.approx(expected, abs=TOLERANCE)


def test_spearman_matches_scipy_with_ties() -> None:
    rng = random.Random(3)
    xs = [float(rng.randint(0, 4)) for _ in range(120)]
    ys = [float(rng.randint(0, 3) * 2 + rng.randint(0, 1)) for _ in range(120)]
    expected = float(stats.spearmanr(xs, ys).statistic)
    assert correlation.spearman(xs, ys) == pytest.approx(expected, abs=TOLERANCE)


def test_spearman_matches_scipy_continuous() -> None:
    xs, ys = _wave(seed=5)
    expected = float(stats.spearmanr(xs, ys).statistic)
    assert correlation.spearman(xs, ys) == pytest.approx(expected, abs=TOLERANCE)


def test_perfect_positive_and_negative() -> None:
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert correlation.pearson(xs, xs) == pytest.approx(1.0, abs=TOLERANCE)
    assert correlation.pearson(xs, [-value for value in xs]) == pytest.approx(-1.0, abs=TOLERANCE)
    assert correlation.spearman(xs, xs) == pytest.approx(1.0, abs=TOLERANCE)
    assert correlation.spearman(xs, [-value for value in xs]) == pytest.approx(-1.0, abs=TOLERANCE)


def test_constant_series_is_undefined_not_nan() -> None:
    ramp = [float(value) for value in range(10)]
    assert correlation.pearson([2.0] * 10, ramp) is None
    assert correlation.spearman([2.0] * 10, list(range(10))) is None
    # 常数序列在 lag 搜索里也不能变成 0 或 NaN。
    lag = correlation.lagged_correlation([2.0] * 10, list(range(10)), lag_max=2)
    assert lag.defined is False
    assert lag.coefficient is None


def test_short_or_mismatched_series_are_undefined() -> None:
    assert correlation.pearson([1.0, 2.0], [1.0, 3.0]) is None
    assert correlation.pearson([1.0, 2.0, 3.0], [1.0, 3.0]) is None
    assert correlation.spearman([1.0, 2.0], [1.0, 3.0]) is None


def test_unknown_method_raises() -> None:
    with pytest.raises(ValueError):
        correlation.correlate([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], "kendall")


def test_same_input_is_bitwise_stable() -> None:
    xs, ys = _wave(seed=17)
    first = correlation.pearson(xs, ys)
    second = correlation.pearson(list(xs), list(ys))
    assert first == second
    first_lag = correlation.lagged_correlation(xs, ys, lag_max=5)
    second_lag = correlation.lagged_correlation(xs, ys, lag_max=5)
    assert first_lag == second_lag


def test_lag_detects_counterparty_leading() -> None:
    base = [math.sin(index / 3.0) for index in range(80)]
    counterparty = list(base)
    target = [0.0, 0.0, 0.0, *base[:-3]]  # 目标是对手方延后 3 根 → 对手方领先
    lag = correlation.lagged_correlation(target, counterparty, lag_max=6)
    assert lag.defined is True
    assert lag.best_lag == 3
    assert lag.coefficient == pytest.approx(1.0, abs=TOLERANCE)
    assert lag.sample_size == len(target) - 3


def test_lag_search_is_clamped_to_available_samples() -> None:
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [2.0, 4.0, 6.0, 8.0]
    lag = correlation.lagged_correlation(xs, ys, lag_max=50)
    # 上限 = n - MIN_SAMPLES = 1，绝不拿不足 3 个点的窗口硬算。
    assert [value for value, _ in lag.by_lag] == [-1, 0, 1]
    assert lag.sample_size >= correlation.MIN_SAMPLES


def test_zero_lag_matches_plain_correlation() -> None:
    xs, ys = _wave(seed=23)
    lag = correlation.lagged_correlation(xs, ys, lag_max=0)
    assert lag.best_lag == 0
    assert lag.coefficient == pytest.approx(correlation.pearson(xs, ys), abs=TOLERANCE)


def test_negative_lag_max_rejected() -> None:
    with pytest.raises(ValueError):
        correlation.lagged_correlation([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], lag_max=-1)


def test_p_value_matches_scipy() -> None:
    xs, ys = _wave(seed=29, n=90)
    coefficient = correlation.pearson(xs, ys)
    assert coefficient is not None
    expected = float(stats.pearsonr(xs, ys).pvalue)
    assert correlation.p_value(coefficient, len(xs)) == pytest.approx(expected, rel=1e-9)


def test_p_value_extremes() -> None:
    assert correlation.p_value(1.0, 10) == 0.0
    assert correlation.p_value(-1.0, 10) == 0.0
    assert correlation.p_value(0.5, 2) is None


def test_rolling_sign_agreement_stable_relationship() -> None:
    xs = [float(index) for index in range(20)]
    ys = [2.0 * value + 1.0 for value in xs]
    assert correlation.rolling_sign_agreement(xs, ys, window=5) == pytest.approx(1.0)


def test_rolling_sign_agreement_returns_none_for_short_window() -> None:
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert correlation.rolling_sign_agreement(xs, xs, window=2) is None
    assert correlation.rolling_sign_agreement(xs, xs, window=6) is None

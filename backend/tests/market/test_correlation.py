"""相关性纯函数（已知答案用例）：Pearson/Spearman、滞后搜索、p 值、稳定性。

参考值来源全部独立于被测实现：

- Pearson 用标准库 `statistics.correlation`（另一套实现）对拍；
- Spearman 用手写秩向量代入 `statistics.correlation` 得到期望值；
- p 值期望值由 t 分布密度函数数值积分（Simpson 法）离线算出后写死在这里；
- 滞后与符号一致率用构造序列的解析解（系数恰为 ±1）。
"""

import math
import random
import statistics

import pytest

from app.market import (
    MIN_SAMPLES,
    correlate,
    lagged_correlation,
    p_value,
    pearson,
    rolling_sign_agreement,
    spearman,
)

TOL = 1e-12


def _wave(n: int = 160, *, seed: int = 11, noise: float = 0.3) -> tuple[list[float], list[float]]:
    """确定性随机扰动的趋势序列：y 与 x 正相关但不是线性复刻。"""

    rng = random.Random(seed)
    xs = [math.sin(index / 7.0) * 3.0 + rng.gauss(0.0, noise) for index in range(n)]
    ys = [0.8 * value + rng.gauss(0.0, noise) for value in xs]
    return xs, ys


# ------------------------------------------------------------------ pearson


@pytest.mark.parametrize("seed", [11, 5, 23])
def test_pearson_matches_stdlib(seed: int) -> None:
    xs, ys = _wave(seed=seed)
    assert pearson(xs, ys) == pytest.approx(statistics.correlation(xs, ys), abs=TOL)


def test_pearson_matches_stdlib_with_many_ties() -> None:
    rng = random.Random(3)
    xs = [float(rng.randint(0, 4)) for _ in range(120)]
    ys = [float(rng.randint(0, 3) * 2 + rng.randint(0, 1)) for _ in range(120)]
    assert pearson(xs, ys) == pytest.approx(statistics.correlation(xs, ys), abs=TOL)


def test_pearson_perfect_positive_and_negative() -> None:
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert pearson(xs, xs) == pytest.approx(1.0, abs=TOL)
    assert pearson(xs, [-value for value in xs]) == pytest.approx(-1.0, abs=TOL)


# ----------------------------------------------------------------- spearman


def test_spearman_matches_hand_written_ranks_with_ties() -> None:
    # 手写平均秩：x=[1,2,2,3,4] → [1, 2.5, 2.5, 4, 5]；y=[10,45,20,15,40] → [1, 5, 3, 2, 4]
    xs = [1.0, 2.0, 2.0, 3.0, 4.0]
    ys = [10.0, 45.0, 20.0, 15.0, 40.0]
    ranks_x = [1.0, 2.5, 2.5, 4.0, 5.0]
    ranks_y = [1.0, 5.0, 3.0, 2.0, 4.0]
    expected = statistics.correlation(ranks_x, ranks_y)
    assert spearman(xs, ys) == pytest.approx(expected, abs=TOL)


def test_spearman_is_rank_based_not_value_based() -> None:
    # 单调非线性变换不改变秩相关，但会改变 Pearson。
    xs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    ys = [value**3 for value in xs]
    assert spearman(xs, ys) == pytest.approx(1.0, abs=TOL)
    assert spearman(xs, [-value for value in ys]) == pytest.approx(-1.0, abs=TOL)
    assert pearson(xs, ys) < 1.0


# ------------------------------------------------------------- 未定义与分派


def test_constant_series_is_undefined_not_nan() -> None:
    ramp = [float(value) for value in range(10)]
    assert pearson([2.0] * 10, ramp) is None
    assert spearman([2.0] * 10, ramp) is None
    lag = lagged_correlation([2.0] * 10, ramp, lag_max=2)
    assert lag.defined is False
    assert lag.coefficient is None
    assert lag.best_lag is None


def test_short_or_mismatched_series_are_undefined() -> None:
    assert pearson([1.0, 2.0], [1.0, 3.0]) is None
    assert pearson([1.0, 2.0, 3.0], [1.0, 3.0]) is None
    assert spearman([1.0, 2.0], [1.0, 3.0]) is None
    assert pearson([1.0, math.inf, 3.0], [1.0, 2.0, 3.0]) is None


def test_unknown_method_raises() -> None:
    with pytest.raises(ValueError, match="unknown correlation method"):
        correlate([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], "kendall")


def test_same_input_is_bitwise_stable() -> None:
    xs, ys = _wave(seed=17)
    assert pearson(xs, ys) == pearson(list(xs), list(ys))
    first = lagged_correlation(xs, ys, lag_max=5)
    second = lagged_correlation(xs, ys, lag_max=5)
    assert first == second


# ------------------------------------------------------------------- 滞后


def test_lag_detects_counterparty_leading() -> None:
    base = [math.sin(index / 3.0) for index in range(80)]
    counterparty = list(base)
    target = [0.0, 0.0, 0.0, *base[:-3]]  # 目标比对手方晚 3 根 → 对手方领先
    lag = lagged_correlation(target, counterparty, lag_max=6)
    assert lag.defined is True
    assert lag.best_lag == 3
    assert lag.coefficient == pytest.approx(1.0, abs=1e-9)
    assert lag.sample_size == len(target) - 3


def test_lag_search_is_clamped_to_available_samples() -> None:
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [2.0, 4.0, 6.0, 8.0]
    lag = lagged_correlation(xs, ys, lag_max=50)
    # 上限 = n - MIN_SAMPLES = 1：绝不拿不足 3 个点的窗口硬算。
    assert [value for value, _ in lag.by_lag] == [-1, 0, 1]
    assert lag.sample_size >= MIN_SAMPLES
    assert lag.best_lag == 0


def test_zero_lag_matches_plain_correlation() -> None:
    xs, ys = _wave(seed=23)
    lag = lagged_correlation(xs, ys, lag_max=0)
    assert lag.best_lag == 0
    assert lag.coefficient == pytest.approx(pearson(xs, ys), abs=TOL)


def test_negative_lag_max_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        lagged_correlation([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], lag_max=-1)


# -------------------------------------------------------------- p 值与稳定性


@pytest.mark.parametrize(
    ("coefficient", "sample_size", "expected"),
    [
        # 由 t 分布密度数值积分（Simpson, 4e5 区间）离线算出的双侧 p 值。
        (0.5, 10, 0.1411133),
        (0.3, 20, 0.1987577),
        (0.7, 15, 0.0036661),
        (0.9, 10, 0.000387156),
    ],
)
def test_p_value_matches_numeric_integration(
    coefficient: float, sample_size: int, expected: float
) -> None:
    value = p_value(coefficient, sample_size)
    assert value is not None
    assert value == pytest.approx(expected, rel=1e-4)


def test_p_value_extremes_and_undefined() -> None:
    assert p_value(1.0, 10) == 0.0
    assert p_value(-1.0, 10) == 0.0
    assert p_value(0.5, 2) is None
    assert p_value(math.nan, 10) is None


def test_rolling_sign_agreement_stable_relationship() -> None:
    xs = [float(index) for index in range(20)]
    ys = [2.0 * value + 1.0 for value in xs]
    assert rolling_sign_agreement(xs, ys, window=5) == pytest.approx(1.0)


def test_rolling_sign_agreement_returns_none_for_short_window() -> None:
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert rolling_sign_agreement(xs, xs, window=2) is None
    assert rolling_sign_agreement(xs, xs, window=6) is None

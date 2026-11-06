"""相关性引擎：Pearson / Spearman、滞后搜索、稳定性（滚动窗口符号一致率）。

只依赖标准库：运行时镜像不装 numpy/scipy，而这里全是 O(n) 的小序列计算。
`numpy`/`scipy` 只在开发测试里作为对拍 oracle（见 `pyproject.toml` 的 dev 依赖）。

术语：
- 「未定义」（undefined）用 `None` 表示，绝不返回 NaN：常数序列、长度不足、
  非有限值都归为未定义。
- 滞后 `lag > 0` 表示**对手方（y）领先目标（x）**：`x[t]` 与 `y[t-lag]` 配对。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import exp, isfinite, lgamma, log, sqrt

METHODS: tuple[str, ...] = ("pearson", "spearman")
# 相关系数需要至少 3 个样本才能给出 t 检验自由度 df = n - 2 >= 1。
MIN_SAMPLES = 3
# 不稳定符号判定的容差：浮点相关系数恰好为 0 的概率极低。
SIGN_EPSILON = 1e-12


def _as_floats(values: Sequence[float]) -> list[float]:
    return [float(value) for value in values]


def _valid_pair(x: Sequence[float], y: Sequence[float]) -> tuple[list[float], list[float]] | None:
    xs = _as_floats(x)
    ys = _as_floats(y)
    if len(xs) != len(ys) or len(xs) < MIN_SAMPLES:
        return None
    if not all(isfinite(value) for value in xs) or not all(isfinite(value) for value in ys):
        return None
    return xs, ys


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _pearson_raw(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """已校验输入的 Pearson 系数；任一序列方差为 0 时返回 `None`。"""

    mean_x = _mean(xs)
    mean_y = _mean(ys)
    covariance = 0.0
    variance_x = 0.0
    variance_y = 0.0
    for value_x, value_y in zip(xs, ys, strict=True):
        delta_x = value_x - mean_x
        delta_y = value_y - mean_y
        covariance += delta_x * delta_y
        variance_x += delta_x * delta_x
        variance_y += delta_y * delta_y
    if variance_x <= 0.0 or variance_y <= 0.0:
        return None
    coefficient = covariance / sqrt(variance_x * variance_y)
    # 浮点误差可能给出 1.0000000000000002，收敛回 [-1, 1]。
    return max(-1.0, min(1.0, coefficient))


def _ranks(values: Sequence[float]) -> list[float]:
    """平均秩（并列取平均），与 `scipy.stats.rankdata(method="average")` 一致。"""

    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        average = (start + end) / 2.0 + 1.0
        for position in range(start, end + 1):
            ranks[order[position]] = average
        start = end + 1
    return ranks


def pearson(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Pearson 相关系数；未定义返回 `None`。"""

    pair = _valid_pair(x, y)
    if pair is None:
        return None
    return _pearson_raw(*pair)


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Spearman 秩相关（并列取平均秩）；未定义返回 `None`。"""

    pair = _valid_pair(x, y)
    if pair is None:
        return None
    xs, ys = pair
    return _pearson_raw(_ranks(xs), _ranks(ys))


def correlate(x: Sequence[float], y: Sequence[float], method: str = "pearson") -> float | None:
    """按方法名分派；未知方法直接报错，避免静默降级成别的口径。"""

    if method == "pearson":
        return pearson(x, y)
    if method == "spearman":
        return spearman(x, y)
    raise ValueError(f"unknown correlation method: {method}")


def _betacf(a: float, b: float, x: float) -> float:
    """正则化不完全 beta 的连分式（Lentz 法，Numerical Recipes 6.4）。"""

    max_iterations = 200
    epsilon = 3e-16
    tiny = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for iteration in range(1, max_iterations + 1):
        m2 = 2 * iteration
        numerator = iteration * (b - iteration) * x / ((qam + m2) * (a + m2))
        d = 1.0 + numerator * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + numerator / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        numerator = -(a + iteration) * (qab + iteration) * x / ((a + m2) * (qap + m2))
        d = 1.0 + numerator * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + numerator / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < epsilon:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """正则化不完全 beta 函数 I_x(a, b)。"""

    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = exp(lgamma(a + b) - lgamma(a) - lgamma(b) + a * log(x) + b * log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def p_value(coefficient: float, sample_size: int) -> float | None:
    """相关系数的双侧 p 值（Student-t，df = n - 2）；无法计算返回 `None`。"""

    if sample_size < MIN_SAMPLES or not isfinite(coefficient):
        return None
    magnitude = min(abs(coefficient), 1.0)
    if magnitude >= 1.0:
        return 0.0
    degrees = sample_size - 2
    t_squared = magnitude * magnitude / (1.0 - magnitude * magnitude) * degrees
    return _betai(degrees / 2.0, 0.5, degrees / (degrees + t_squared))


@dataclass(frozen=True, slots=True)
class LaggedCorrelation:
    """带滞后搜索的相关结果；`best_lag` 为 `None` 表示全窗口都未定义。"""

    best_lag: int | None
    coefficient: float | None
    p_value: float | None
    sample_size: int
    by_lag: tuple[tuple[int, float | None], ...]

    @property
    def defined(self) -> bool:
        return self.coefficient is not None


def lagged_correlation(
    x: Sequence[float],
    y: Sequence[float],
    *,
    lag_max: int = 0,
    method: str = "pearson",
) -> LaggedCorrelation:
    """在 `[-lag_max, +lag_max]` 内搜索 |r| 最大的滞后。

    正 lag = 对手方领先目标。样本量随 |lag| 减少，因此 lag 上限受
    `n - MIN_SAMPLES` 约束，绝不截断硬算不足 3 个点的窗口。
    """

    if lag_max < 0:
        raise ValueError("lag_max must be non-negative")
    xs = _as_floats(x)
    ys = _as_floats(y)
    n = min(len(xs), len(ys))
    if n < MIN_SAMPLES:
        return LaggedCorrelation(None, None, None, n, ())
    xs = xs[:n]
    ys = ys[:n]
    limit = min(lag_max, n - MIN_SAMPLES)
    by_lag: list[tuple[int, float | None]] = []
    for lag in range(-limit, limit + 1):
        if lag >= 0:
            coefficient = correlate(xs[lag:], ys[: n - lag], method)
        else:
            offset = -lag
            coefficient = correlate(xs[: n - offset], ys[offset:], method)
        by_lag.append((lag, coefficient))
    defined = [(lag, coefficient) for lag, coefficient in by_lag if coefficient is not None]
    if not defined:
        return LaggedCorrelation(None, None, None, 0, tuple(by_lag))
    # 确定性排序：|r| 最大 → |lag| 最小 → lag 最小（负在前），避免同分抖动。
    best_lag, best_coefficient = min(
        defined, key=lambda item: (-abs(item[1]), abs(item[0]), item[0])
    )
    sample_size = n - abs(best_lag)
    return LaggedCorrelation(
        best_lag=best_lag,
        coefficient=best_coefficient,
        p_value=p_value(best_coefficient, sample_size),
        sample_size=sample_size,
        by_lag=tuple(by_lag),
    )


def _sign(value: float) -> int:
    if value > SIGN_EPSILON:
        return 1
    if value < -SIGN_EPSILON:
        return -1
    return 0


def rolling_sign_agreement(
    x: Sequence[float],
    y: Sequence[float],
    *,
    window: int,
    method: str = "pearson",
) -> float | None:
    """稳定性：滚动窗口相关系数的符号与全样本符号的一致率。

    - 全样本或每个窗口的相关系数都可能未定义，未定义窗口跳过；
    - 没有可用窗口或窗口小于 3 时返回 `None`；
    - 一致率 1.0 表示关系符号始终稳定，0.5 表示约一半窗口反向。
    """

    pair = _valid_pair(x, y)
    if pair is None or window < MIN_SAMPLES:
        return None
    xs, ys = pair
    n = len(xs)
    if window > n:
        return None
    full = _pearson_raw(xs, ys) if method == "pearson" else correlate(xs, ys, method)
    if full is None:
        return None
    full_sign = _sign(full)
    matches = 0
    considered = 0
    for start in range(0, n - window + 1):
        coefficient = correlate(xs[start : start + window], ys[start : start + window], method)
        if coefficient is None:
            continue
        considered += 1
        if _sign(coefficient) == full_sign:
            matches += 1
    if considered == 0:
        return None
    return matches / considered


__all__ = [
    "METHODS",
    "MIN_SAMPLES",
    "LaggedCorrelation",
    "correlate",
    "lagged_correlation",
    "p_value",
    "pearson",
    "rolling_sign_agreement",
    "spearman",
]

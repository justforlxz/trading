"""资产聚类（P1-12）：相关距离矩阵 + 平均连接层次聚类 + 轮廓系数。

只依赖标准库与 `app.analysis.core.correlation.pearson`。所有函数是纯函数：
输入是「标的 → {时间戳: 对数收益率}」，输出是聚类结果，不碰数据库、不看时钟。

口径：

- 相关距离 `d = 1 - r`，取值 `[0, 2]`；`r = 1` 表示同涨同跌（距离 0），
  `r = 0` 表示无线性关系（距离 1），`r = -1` 表示完全反向（距离 2）。
- **相关不可计算时（样本不足、常数序列）按 `d = 1` 参与聚类，并在结果里记录
  `undefined_pairs`**。这不是把「未定义」当成「0 相关」写进业务值——距离只是聚类
  的输入，且 1 恰好让这类标的天然不会被并入强相关簇；真实原因由 `undefined_pairs`
  如实上报，绝不静默。
- 平均连接（average linkage）：簇间距离取成员两两距离的均值；每次合并后按
  `(n_a*d(a,k) + n_b*d(b,k)) / (n_a+n_b)` 递推，避免 O(n^3) 全量重算。
- 剪枝阈值 `threshold` 是距离阈值（默认 0.7 表示平均 `r >= 0.3` 才并簇）。
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from math import comb
from typing import Any

from app.analysis.core.correlation import pearson

UNDEFINED_DISTANCE = 1.0


@dataclass(frozen=True, slots=True)
class DistanceMatrix:
    """`keys` 与 `values` 行列一一对应；`undefined_pairs` 是无法计算相关的对数。"""

    keys: tuple[Any, ...]
    values: tuple[tuple[float, ...], ...]
    undefined_pairs: int

    @property
    def size(self) -> int:
        return len(self.keys)


@dataclass(frozen=True, slots=True)
class ClusterMember:
    """簇内成员：到其他成员的平均距离与平均相关系数（= 1 - distance）。"""

    key: Any
    distance: float
    correlation: float


@dataclass(frozen=True, slots=True)
class Cluster:
    members: tuple[ClusterMember, ...]
    silhouette: float | None

    @property
    def size(self) -> int:
        return len(self.members)


@dataclass(frozen=True, slots=True)
class ClusteringResult:
    clusters: tuple[Cluster, ...]
    matrix: DistanceMatrix

    @property
    def undefined_pairs(self) -> int:
        return self.matrix.undefined_pairs


def pairwise_distance(
    points: Mapping[Hashable, Mapping[datetime, float]],
    *,
    min_overlap: int = 3,
) -> DistanceMatrix:
    """按时间戳交集对齐后计算两两相关距离。

    每个标的只提供自己有的时间戳；不同标的上市日期不同，用交集而不是并集，
    避免用缺失值填充后算出虚假相关。
    """

    keys = tuple(sorted(points, key=lambda key: str(key)))
    size = len(keys)
    values: list[list[float]] = [[0.0] * size for _ in range(size)]
    undefined_pairs = 0
    for left in range(size):
        for right in range(left + 1, size):
            left_series = points[keys[left]]
            right_series = points[keys[right]]
            common = sorted(left_series.keys() & right_series.keys())
            distance = UNDEFINED_DISTANCE
            if len(common) >= min_overlap:
                coefficient = pearson(
                    [left_series[ts] for ts in common],
                    [right_series[ts] for ts in common],
                )
                if coefficient is None:
                    undefined_pairs += 1
                else:
                    distance = 1.0 - coefficient
            else:
                undefined_pairs += 1
            values[left][right] = distance
            values[right][left] = distance
    return DistanceMatrix(
        keys=keys,
        values=tuple(tuple(row) for row in values),
        undefined_pairs=undefined_pairs,
    )


def average_linkage(matrix: DistanceMatrix, threshold: float) -> list[list[int]]:
    """平均连接层次聚类；簇间平均距离大于阈值即停止合并。"""

    size = matrix.size
    if size == 0:
        return []
    clusters: dict[int, list[int]] = {index: [index] for index in range(size)}
    counts: dict[int, int] = {index: 1 for index in range(size)}
    linkage: dict[tuple[int, int], float] = {}
    for left in range(size):
        for right in range(left + 1, size):
            linkage[(left, right)] = matrix.values[left][right]

    while len(clusters) > 1:
        (left, right), best = min(linkage.items(), key=lambda item: (item[1], item[0]))
        if best > threshold:
            break
        left_count = counts[left]
        right_count = counts[right]
        # 先摘掉旧键：合并后 (left,*) / (right,*) 的距离都要按簇规模重新递推。
        stale = [pair for pair in linkage if left in pair or right in pair]
        previous = {pair: linkage[pair] for pair in stale}
        for pair in stale:
            del linkage[pair]
        clusters[left] = clusters[left] + clusters[right]
        counts[left] = left_count + right_count
        del clusters[right]
        del counts[right]
        for other in clusters:
            if other == left:
                continue
            key_left_right = (min(left, other), max(left, other))
            key_right_other = (min(right, other), max(right, other))
            averaged = (
                left_count * previous[key_left_right] + right_count * previous[key_right_other]
            ) / (left_count + right_count)
            linkage[(min(left, other), max(left, other))] = averaged
    return list(clusters.values())


def silhouette(matrix: DistanceMatrix, clusters: Sequence[Sequence[int]]) -> float | None:
    """平均轮廓系数；单簇或全为单点簇时未定义。"""

    if len(clusters) < 2:
        return None
    scores: list[float] = []
    for label, members in enumerate(clusters):
        if len(members) < 2:
            continue
        for member in members:
            inner = [other for other in members if other != member]
            a = sum(matrix.values[member][other] for other in inner) / len(inner)
            b = min(
                sum(matrix.values[member][other] for other in others) / len(others)
                for index, others in enumerate(clusters)
                if index != label
            )
            denominator = max(a, b)
            if denominator <= 0.0:
                continue
            scores.append((b - a) / denominator)
    if not scores:
        return None
    return sum(scores) / len(scores)


def adjusted_rand_index(labels_true: Sequence[Any], labels_pred: Sequence[Any]) -> float:
    """调整兰德指数：衡量两组划分的一致性，1 表示完全一致，0 表示随机水平。

    既是聚类质量的度量，也是测试里的已知答案 oracle（不依赖 sklearn）。
    """

    if len(labels_true) != len(labels_pred):
        raise ValueError("labels_true and labels_pred must have the same length")
    total = len(labels_true)
    if total < 2:
        return 1.0

    def _contingency(first: Sequence[Any], second: Sequence[Any]) -> dict[tuple[Any, Any], int]:
        counts: dict[tuple[Any, Any], int] = {}
        for left, right in zip(first, second, strict=True):
            counts[(left, right)] = counts.get((left, right), 0) + 1
        return counts

    def _pairs(groups: Sequence[Any]) -> int:
        counts: dict[Any, int] = {}
        for group in groups:
            counts[group] = counts.get(group, 0) + 1
        return sum(comb(count, 2) for count in counts.values())

    pairs_both = sum(comb(count, 2) for count in _contingency(labels_true, labels_pred).values())
    pairs_true = _pairs(labels_true)
    pairs_pred = _pairs(labels_pred)
    total_pairs = comb(total, 2)
    expected = pairs_true * pairs_pred / total_pairs
    maximum = (pairs_true + pairs_pred) / 2.0
    if maximum == expected:
        return 1.0
    return (pairs_both - expected) / (maximum - expected)


def cluster(
    points: Mapping[Hashable, Mapping[datetime, float]],
    *,
    threshold: float,
    min_overlap: int = 3,
    min_size: int = 2,
) -> ClusteringResult:
    """一次完整的聚类：相关距离 → 平均连接 → 轮廓系数 → 丢弃过小的簇。"""

    matrix = pairwise_distance(points, min_overlap=min_overlap)
    raw = average_linkage(matrix, threshold)
    kept = [members for members in raw if len(members) >= min_size]
    silhouette_score = silhouette(matrix, raw)
    clusters: list[Cluster] = []
    for members in kept:
        detail: list[ClusterMember] = []
        for member in members:
            others = [other for other in members if other != member]
            if others:
                distance = sum(matrix.values[member][other] for other in others) / len(others)
            else:
                distance = 0.0
            detail.append(
                ClusterMember(
                    key=matrix.keys[member],
                    distance=distance,
                    correlation=1.0 - distance,
                )
            )
        detail.sort(key=lambda item: item.distance)
        clusters.append(Cluster(members=tuple(detail), silhouette=silhouette_score))
    clusters.sort(key=lambda item: (-item.size, str(item.members[0].key)))
    return ClusteringResult(clusters=tuple(clusters), matrix=matrix)


__all__ = [
    "UNDEFINED_DISTANCE",
    "Cluster",
    "ClusterMember",
    "ClusteringResult",
    "DistanceMatrix",
    "adjusted_rand_index",
    "average_linkage",
    "cluster",
    "pairwise_distance",
    "silhouette",
]

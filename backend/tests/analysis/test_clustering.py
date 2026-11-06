"""聚类纯函数单测（P1-12）：合成数据 ARI、成员唯一性与未定义对计数。"""

import random
from datetime import UTC, datetime, timedelta

import pytest

from app.analysis.core import clustering

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _synthetic(seed: int = 20261106):
    """三簇合成数据：簇内共享潜在因子，簇间独立。"""

    rng = random.Random(seed)
    days = 60
    points: dict[int, dict[datetime, float]] = {}
    truth: dict[int, int] = {}
    for group in range(3):
        factor = [rng.gauss(0.0, 0.015) for _ in range(days)]
        for member in range(4):
            key = group * 10 + member
            truth[key] = group
            points[key] = {
                BASE + timedelta(days=index): factor[index] + rng.gauss(0.0, 0.002)
                for index in range(days)
            }
    return points, truth


def test_three_clear_clusters_recover_truth_with_high_ari() -> None:
    points, truth = _synthetic()
    result = clustering.cluster(points, threshold=0.5, min_overlap=20, min_size=2)

    predicted: dict[int, int] = {}
    for label, grouped in enumerate(result.clusters):
        for member in grouped.members:
            predicted[member.key] = label

    keys = sorted(truth)
    labels_true = [truth[key] for key in keys]
    labels_pred = [predicted[key] for key in keys]
    score = clustering.adjusted_rand_index(labels_true, labels_pred)

    assert len(result.clusters) == 3
    assert score > 0.9
    assert result.undefined_pairs == 0


def test_each_instrument_belongs_to_exactly_one_cluster() -> None:
    points, _ = _synthetic()
    result = clustering.cluster(points, threshold=0.5, min_overlap=20, min_size=2)

    seen = [member.key for grouped in result.clusters for member in grouped.members]
    assert len(seen) == len(set(seen))
    assert set(seen) == set(points)


def test_small_clusters_are_dropped_but_undefined_pairs_are_counted() -> None:
    points, _ = _synthetic()
    # 常数序列与谁都无法计算相关：距离按 1.0 参与，并如实计入 undefined_pairs。
    points[999] = {BASE + timedelta(days=index): 0.0 for index in range(60)}
    result = clustering.cluster(points, threshold=0.5, min_overlap=20, min_size=3)

    assert result.undefined_pairs >= 1
    assert all(grouped.size >= 3 for grouped in result.clusters)
    assert 999 not in [member.key for grouped in result.clusters for member in grouped.members]


def test_silhouette_is_within_its_definition_range() -> None:
    points, _ = _synthetic()
    result = clustering.cluster(points, threshold=0.5, min_overlap=20, min_size=2)
    for grouped in result.clusters:
        assert grouped.silhouette is not None
        assert -1.0 <= grouped.silhouette <= 1.0


def test_average_linkage_merges_only_within_threshold() -> None:
    matrix = clustering.DistanceMatrix(
        keys=(0, 1, 2),
        values=((0.0, 0.2, 0.9), (0.2, 0.0, 0.9), (0.9, 0.9, 0.0)),
        undefined_pairs=0,
    )
    assert clustering.average_linkage(matrix, threshold=0.5) == [[0, 1], [2]]
    assert clustering.average_linkage(matrix, threshold=0.1) == [[0], [1], [2]]


def test_adjusted_rand_index_known_answers() -> None:
    assert clustering.adjusted_rand_index([0, 0, 1, 1], [7, 7, 8, 8]) == pytest.approx(1.0)
    # 完全错配（每个簇都只是另一簇的一半）时 ARI 为 -0.5。
    assert clustering.adjusted_rand_index([0, 0, 1, 1], [0, 1, 0, 1]) == pytest.approx(-0.5)


def test_short_overlap_counts_as_undefined_pair() -> None:
    points = {
        1: {BASE + timedelta(days=index): float(index) for index in range(40)},
        2: {BASE + timedelta(days=index): float(index) for index in range(5)},
    }
    matrix = clustering.pairwise_distance(points, min_overlap=10)
    assert matrix.undefined_pairs == 1
    assert matrix.values[0][1] == pytest.approx(clustering.UNDEFINED_DISTANCE)

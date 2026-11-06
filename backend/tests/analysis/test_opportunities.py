"""机会生成纯函数单测（P1-13）：可解释性、方向正确性与去重键稳定性。"""

import random
from datetime import UTC, datetime, timedelta

import pytest

from app.analysis.core import opportunities as core

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def member(
    instrument_id: int,
    ret_1d: float | None,
    ret_5d: float | None = None,
    correlation: float = 0.8,
) -> core.MemberFeature:
    return core.MemberFeature(
        instrument_id=instrument_id,
        inst_id=f"SYM{instrument_id}-USDT-SWAP",
        symbol=f"SYM{instrument_id}",
        ret_1d=ret_1d,
        ret_5d=ret_5d if ret_5d is not None else ret_1d,
        ret_20d=None,
        vol_20d=0.02,
        distance=1.0 - correlation,
        correlation=correlation,
    )


def test_directional_candidate_is_explainable_and_directional() -> None:
    members = [member(1, 0.03), member(2, 0.02), member(3, 0.01), member(4, 0.04), member(5, -0.01)]

    candidates = core.directional_candidates(
        [("cluster-01", members, 0.55)], strength_threshold=0.6
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.kind == core.KIND_DIRECTIONAL
    assert candidate.direction == "long"
    assert len(candidate.reasons) >= 2
    assert candidate.evidence["resonance_strength"] == pytest.approx(0.8)
    assert candidate.evidence["mean_ret_5d"] > 0
    assert len(candidate.member_ids) == 4
    assert all(str(reason).strip() for reason in candidate.reasons)


def test_weak_resonance_produces_no_candidate() -> None:
    members = [member(1, 0.03), member(2, 0.02), member(3, -0.01), member(4, -0.02)]

    assert (
        core.directional_candidates([("cluster-01", members, None)], strength_threshold=0.6) == []
    )


def test_score_is_monotonic_in_resonance_strength() -> None:
    weak = [member(index, 0.01) for index in range(1, 7)] + [
        member(index, -0.01) for index in range(7, 11)
    ]
    strong = [member(index, 0.01) for index in range(1, 10)] + [member(10, -0.01)]

    weak_candidate = core.directional_candidates([("cluster-01", weak, None)])[0]
    strong_candidate = core.directional_candidates([("cluster-01", strong, None)])[0]

    assert strong_candidate.score > weak_candidate.score


def test_pair_candidate_points_from_rich_to_cheap() -> None:
    rng = random.Random(7)
    common = [0.0]
    for _ in range(199):
        common.append(common[-1] + rng.gauss(0.0, 0.01))
    left = {BASE + timedelta(days=index): value for index, value in enumerate(common)}
    right = {
        BASE + timedelta(days=index): value + rng.gauss(0.0, 0.001)
        for index, value in enumerate(common)
    }
    # 让左腿在最后一根明显偏贵：价差 z 值为正 → 做空左腿。
    left[BASE + timedelta(days=199)] += 0.06

    candidates = core.pair_candidates(
        [("cluster-01", [member(1, 0.01), member(2, 0.01)], None)],
        {1: left, 2: right},
        min_correlation=0.6,
        z_threshold=1.0,
        min_overlap=30,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.kind == core.KIND_RELATIVE_VALUE
    assert candidate.direction == "pair"
    assert candidate.evidence["short_instrument_id"] == 1
    assert candidate.evidence["long_instrument_id"] == 2
    assert candidate.evidence["spread_z"] > 0
    assert candidate.evidence["overlap_bars"] == 200
    assert candidate.reasons


def test_low_correlation_pairs_are_skipped() -> None:
    rng = random.Random(9)
    left = {BASE + timedelta(days=index): rng.gauss(0.0, 1.0) for index in range(120)}
    right = {BASE + timedelta(days=index): rng.gauss(0.0, 1.0) for index in range(120)}

    candidates = core.pair_candidates(
        [("cluster-01", [member(1, 0.01), member(2, 0.01)], None)],
        {1: left, 2: right},
        min_correlation=0.6,
        z_threshold=0.1,
        min_overlap=30,
    )
    assert candidates == []


def test_assert_explainable_rejects_bare_scores() -> None:
    with pytest.raises(core.UnexplainableCandidate):
        core.assert_explainable([], {"score": 0.9})
    with pytest.raises(core.UnexplainableCandidate):
        core.assert_explainable(["说明"], {"cluster": "cluster-01"})
    core.assert_explainable(["说明"], {"cluster": "cluster-01", "strength": 0.8})


def test_candidate_key_is_order_insensitive_and_direction_aware() -> None:
    first = core.candidate_key("directional", "long", [3, 1, 2])
    second = core.candidate_key("directional", "long", [1, 2, 3])
    short = core.candidate_key("directional", "short", [1, 2, 3])

    assert first == second
    assert first != short

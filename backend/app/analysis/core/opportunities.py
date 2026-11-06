"""机会生成与打分（P1-13）：把「群体共振」与「相对偏离」变成可解释的候选。

这里只做决策计算，不读数据库、不看时钟：

- `directional_candidates`：簇内多数成员同向运动 → 方向性机会；
- `pair_candidates`：簇内高相关两只标的的价差 z 值足够大 → 相对价值机会，
  同时把「相关性突变」写进证据，而不是另起一类无法解释的机会。

每个候选都必须带非空 `reasons`（人类可读）与 `evidence`（可复算的原始量），
`assert_explainable` 在落库与响应构造两处强制这一点：**不允许出现裸分数**。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from math import isfinite
from typing import Any

from app.analysis.core.correlation import MIN_SAMPLES, pearson
from app.analysis.core.resonance import (
    Breadth,
    breadth,
    correlation_shift,
    resonance,
)

KIND_DIRECTIONAL = "directional"
KIND_RELATIVE_VALUE = "relative_value"
DIRECTIONS = ("long", "short", "pair")
HORIZON_DEFAULT = "5d"


class UnexplainableCandidate(ValueError):
    """机会缺少理由或证据；宁可失败也不落一条无法解释的记录。"""


@dataclass(frozen=True, slots=True)
class MemberFeature:
    """聚类成员在截面上的可用特征（缺失用 `None` 表达）。"""

    instrument_id: int
    inst_id: str
    symbol: str
    ret_1d: float | None
    ret_5d: float | None
    ret_20d: float | None
    vol_20d: float | None
    distance: float
    correlation: float


@dataclass(frozen=True, slots=True)
class Candidate:
    """一条待落库的机会；`dedupe_key` 由成员集合与方向规范化得到。"""

    kind: str
    direction: str
    primary_instrument_id: int
    score: float
    horizon: str
    reasons: tuple[str, ...]
    evidence: dict[str, Any]
    member_ids: tuple[int, ...]
    dedupe_key: str


def candidate_key(kind: str, direction: str, member_ids: Sequence[int]) -> str:
    """去重键：成员集合 + 方向 + 类型；与顺序无关，保证重跑不产生副本。"""

    payload = {
        "kind": kind,
        "direction": direction,
        "members": sorted({int(member) for member in member_ids}),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def assert_explainable(reasons: Sequence[str], evidence: Mapping[str, Any]) -> None:
    """机会必须能回答「为什么是它」：理由非空，证据里至少有一个可复算数值。"""

    if not reasons or not any(str(reason).strip() for reason in reasons):
        raise UnexplainableCandidate("opportunity has no human-readable reasons")
    numeric = [
        value
        for value in evidence.values()
        if isinstance(value, int | float) and not isinstance(value, bool) and isfinite(value)
    ]
    if not numeric:
        raise UnexplainableCandidate("opportunity evidence has no recomputable numeric value")


def _fmt_percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2%}"


def _breadth_payload(counts: Breadth) -> dict[str, Any]:
    return {
        "up": counts.up,
        "down": counts.down,
        "flat": counts.flat,
        "total": counts.total,
        "up_ratio": counts.up_ratio,
        "down_ratio": counts.down_ratio,
    }


def _member_payload(member: MemberFeature) -> dict[str, Any]:
    return {
        "instrument_id": member.instrument_id,
        "inst_id": member.inst_id,
        "symbol": member.symbol,
        "ret_1d": member.ret_1d,
        "ret_5d": member.ret_5d,
        "ret_20d": member.ret_20d,
        "vol_20d": member.vol_20d,
        "distance": member.distance,
        "correlation": member.correlation,
    }


def directional_candidates(
    clusters: Sequence[tuple[str, Sequence[MemberFeature], float | None]],
    *,
    strength_threshold: float = 0.6,
    min_members: int = 2,
) -> list[Candidate]:
    """簇内共振 → 方向性机会。

    `strength` 是同向成员占比；`score = strength * (1 + |簇内 5 日平均收益|)`，
    让「同向且幅度大」排在前，同时保持对同向比例的单调性。
    """

    candidates: list[Candidate] = []
    for label, members, silhouette in clusters:
        if len(members) < min_members:
            continue
        with_return = [member for member in members if member.ret_1d is not None]
        if len(with_return) < min_members:
            continue
        conclusion = resonance([member.ret_1d or 0.0 for member in with_return])
        if not conclusion.defined or conclusion.direction is None:
            continue
        strength = conclusion.strength
        if strength is None or strength < strength_threshold:
            continue
        direction = conclusion.direction
        sign = 1.0 if direction == "long" else -1.0
        aligned = [member for member in with_return if (member.ret_1d or 0.0) * sign > 0.0]
        if len(aligned) < min_members:
            continue
        returns = [member.ret_5d for member in aligned if member.ret_5d is not None]
        mean_return = sum(returns) / len(returns) if returns else None
        fallback = [member.ret_1d for member in aligned if member.ret_1d is not None]
        if mean_return is None and fallback:
            mean_return = sum(fallback) / len(fallback)
        if mean_return is None:
            continue
        score = strength * (1.0 + abs(mean_return))
        leader = max(
            aligned,
            key=lambda member: (member.ret_5d if member.ret_5d is not None else 0.0) * sign,
        )
        reasons = [
            f"{len(aligned)}/{len(members)} 只标的同向({('上涨' if sign > 0 else '下跌')}),"
            f"共振强度 {strength:.2%}",
            f"簇内 5 日平均收益 {_fmt_percent(mean_return)}, 主导标的 {leader.symbol}"
            f" {_fmt_percent(leader.ret_5d)}",
        ]
        if silhouette is not None:
            reasons.append(f"聚类轮廓系数 {silhouette:.3f}")
        evidence: dict[str, Any] = {
            "cluster": label,
            "cluster_size": len(members),
            "resonance_strength": strength,
            "direction": direction,
            "mean_ret_5d": mean_return,
            "leader_ret_5d": leader.ret_5d,
            "breadth": _breadth_payload(conclusion.breadth),
            "members": [_member_payload(member) for member in aligned],
        }
        member_ids = tuple(member.instrument_id for member in aligned)
        assert_explainable(reasons, evidence)
        candidates.append(
            Candidate(
                kind=KIND_DIRECTIONAL,
                direction=direction,
                primary_instrument_id=leader.instrument_id,
                score=score,
                horizon=HORIZON_DEFAULT,
                reasons=tuple(reasons),
                evidence=evidence,
                member_ids=member_ids,
                dedupe_key=candidate_key(KIND_DIRECTIONAL, direction, member_ids),
            )
        )
    candidates.sort(key=lambda item: (-item.score, item.dedupe_key))
    return candidates


def _aligned_spread(
    left: Mapping[datetime, float],
    right: Mapping[datetime, float],
) -> list[tuple[datetime, float, float]]:
    """按共同时间戳对齐（价格取自然对数，价差即对数比值）。"""

    common = sorted(left.keys() & right.keys())
    return [(ts, left[ts], right[ts]) for ts in common]


def _z_score(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    if variance <= 0.0:
        return None
    return (values[-1] - mean) / (variance**0.5)


def _correlation_of(levels: Sequence[tuple[datetime, float, float]]) -> float | None:
    left = [left_value for _, left_value, _ in levels]
    right = [right_value for _, _, right_value in levels]
    left_returns = [end - start for start, end in pairwise(left)]
    right_returns = [end - start for start, end in pairwise(right)]
    return pearson(left_returns, right_returns)


def pair_candidates(
    clusters: Sequence[tuple[str, Sequence[MemberFeature], float | None]],
    levels: Mapping[int, Mapping[datetime, float]],
    *,
    min_correlation: float = 0.6,
    z_threshold: float = 1.5,
    min_overlap: int = 30,
    anomaly_window: int = 20,
    anomaly_min_abs: float = 0.7,
    anomaly_min_delta: float = 0.4,
    max_pairs: int = 40,
) -> list[Candidate]:
    """簇内高相关标的的价差偏离 → 相对价值机会（含相关性突变证据）。

    `levels` 是「instrument_id → {时间戳: 对数价格}」。价差 z 值为正说明
    前者相对后者偏贵：做空前者、做多后者；为负则相反。
    """

    candidates: list[Candidate] = []
    seen: set[tuple[int, int]] = set()
    for label, members, silhouette in clusters:
        for index, left in enumerate(members):
            left_levels = levels.get(left.instrument_id)
            if not left_levels:
                continue
            for right in members[index + 1 :]:
                right_levels = levels.get(right.instrument_id)
                if not right_levels:
                    continue
                pair_key = tuple(sorted((left.instrument_id, right.instrument_id)))
                if pair_key in seen:
                    continue
                aligned = _aligned_spread(left_levels, right_levels)
                if len(aligned) < max(min_overlap, MIN_SAMPLES + 1):
                    continue
                correlation = _correlation_of(aligned)
                if correlation is None or correlation < min_correlation:
                    continue
                seen.add(pair_key)
                spreads = [left_value - right_value for _, left_value, right_value in aligned]
                z_score = _z_score(spreads)
                shift = correlation_shift(
                    [left_value for _, left_value, _ in aligned],
                    [right_value for _, _, right_value in aligned],
                    window=anomaly_window,
                    min_abs=anomaly_min_abs,
                    min_delta=anomaly_min_delta,
                )
                if z_score is None:
                    continue
                if abs(z_score) < z_threshold and not shift.flagged:
                    continue
                if z_score > 0.0:
                    hot, cheap = left, right
                else:
                    hot, cheap = right, left
                score = abs(z_score) * abs(correlation) + (0.25 if shift.flagged else 0.0)
                reasons = [
                    f"{hot.symbol} 相对 {cheap.symbol} 的价差偏离 {z_score:+.2f} 个标准差",
                    f"两者相关 {correlation:.3f}({len(aligned)} 个共同样本)",
                    f"做空 {hot.symbol} / 做多 {cheap.symbol}",
                ]
                evidence: dict[str, Any] = {
                    "cluster": label,
                    "spread_z": z_score,
                    "correlation": correlation,
                    "overlap_bars": len(aligned),
                    "long_inst_id": cheap.inst_id,
                    "short_inst_id": hot.inst_id,
                    "long_instrument_id": cheap.instrument_id,
                    "short_instrument_id": hot.instrument_id,
                }
                if silhouette is not None:
                    evidence["silhouette"] = silhouette
                if shift.defined:
                    evidence["anomaly"] = {
                        "flagged": shift.flagged,
                        "window": shift.window,
                        "baseline": shift.baseline,
                        "recent": shift.recent,
                        "delta": shift.delta,
                    }
                    if shift.flagged:
                        reasons.append(
                            f"相关性突变: {shift.window} 根窗口内由 "
                            f"{shift.baseline:.3f} 升到 {shift.recent:.3f}"
                        )
                assert_explainable(reasons, evidence)
                candidates.append(
                    Candidate(
                        kind=KIND_RELATIVE_VALUE,
                        direction="pair",
                        primary_instrument_id=cheap.instrument_id,
                        score=score,
                        horizon=HORIZON_DEFAULT,
                        reasons=tuple(reasons),
                        evidence=evidence,
                        member_ids=pair_key,
                        dedupe_key=candidate_key(KIND_RELATIVE_VALUE, "pair", pair_key),
                    )
                )
    candidates.sort(key=lambda item: (-item.score, item.dedupe_key))
    return candidates[:max_pairs]


def market_breadth(returns: Sequence[float]) -> dict[str, Any]:
    """全市场广度（驾驶舱用）；单独导出避免前端自行计算。"""

    return _breadth_payload(breadth(returns))


__all__ = [
    "DIRECTIONS",
    "HORIZON_DEFAULT",
    "KIND_DIRECTIONAL",
    "KIND_RELATIVE_VALUE",
    "Candidate",
    "MemberFeature",
    "UnexplainableCandidate",
    "assert_explainable",
    "candidate_key",
    "directional_candidates",
    "market_breadth",
    "pair_candidates",
]

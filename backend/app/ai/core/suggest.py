"""策略草案建议: 只根据关系快照产生候选腿, 不落库、不提交审批。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEFAULT_MAX_WEIGHT = 0.5


def build_legs(
    edges: list[Mapping[str, Any]],
    *,
    max_weight: float = DEFAULT_MAX_WEIGHT,
) -> list[dict[str, Any]]:
    positive = [row for row in edges if _as_float(row.get("coefficient")) > 0]
    negative = [row for row in edges if _as_float(row.get("coefficient")) < 0]
    best_positive = max(positive, key=lambda row: _as_float(row.get("coefficient")), default=None)
    best_negative = min(negative, key=lambda row: _as_float(row.get("coefficient")), default=None)
    picks: list[tuple[str, Mapping[str, Any]]] = []
    if best_positive is not None:
        picks.append(("long", best_positive))
    if best_negative is not None:
        picks.append(("short", best_negative))
    if not picks:
        return []

    weight = min(max_weight, 0.5 if len(picks) == 2 else max_weight)
    legs: list[dict[str, Any]] = []
    for side, edge in picks:
        coefficient = edge.get("coefficient")
        best_lag = edge.get("best_lag")
        legs.append(
            {
                "instrument_id": edge.get("instrument_id"),
                "inst_id": edge.get("inst_id"),
                "side": side,
                "target_weight": f"{weight:.2f}",
                "rationale": f"关系系数 {coefficient}, 最优滞后 {best_lag}",
            }
        )
    return legs


def suggest_summary(*, target_id: int, legs: list[Mapping[str, Any]]) -> str:
    if not legs:
        return (
            f"数据不足: 目标 {target_id} 的关系快照没有可用于构建草案的显著边。"
            "缺失项: relation_edges"
        )
    detail = ", ".join(
        f"{leg.get('side')} {leg.get('inst_id')} 权重 {leg.get('target_weight')}" for leg in legs
    )
    return f"基于目标 {target_id} 的关系快照生成草案 (未落库) : {detail}。"


def warnings_for(legs: list[Mapping[str, Any]]) -> list[str]:
    items = ["草案仅供人工评审, 未落库、未提交审批, 不构成交易指令"]
    if len(legs) < 2:
        items.append("当前只有单边候选, 需人工补齐对手腿后再评审")
    return items


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["DEFAULT_MAX_WEIGHT", "build_legs", "suggest_summary", "warnings_for"]

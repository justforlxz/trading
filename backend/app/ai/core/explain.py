"""市场时段与关系快照的确定性解释文本与引用。

所有数值都来自调用方从 `market`/`research` 服务读到的结果, 本模块只做格式化,
不做任何重算。
"""

from __future__ import annotations

from typing import Any

from app.ai.core.citations import citation


def session_source() -> str:
    return "GET /api/v1/market/sessions"


def coverage_source() -> str:
    return "GET /api/v1/market/coverage"


def relations_source(target_id: int) -> str:
    return f"GET /api/v1/targets/{target_id}/relations"


def market_citations(
    *,
    sessions: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
    target_count: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in sessions:
        items.append(
            citation(
                "market_session",
                session_source(),
                venue=row.get("venue"),
                trading_date=row.get("trading_date"),
                is_session=row.get("is_session"),
                regular_start=row.get("regular_start"),
                regular_end=row.get("regular_end"),
            )
        )
    for block in coverage:
        summary = block.get("summary") or {}
        items.append(
            citation(
                "market_coverage",
                coverage_source(),
                instrument_id=block.get("inst_id"),
                bar=block.get("bar"),
                expected=summary.get("expected"),
                actual=summary.get("actual"),
                missing=summary.get("missing"),
                ratio=summary.get("ratio"),
            )
        )
    items.append(citation("target_universe", "GET /api/v1/targets", target_count=target_count))
    return items


def market_summary(
    *,
    sessions: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
    target_count: int,
    bar: str,
) -> str:
    if not coverage:
        return (
            "数据不足: 没有可解释的行情覆盖, 缺少 enabled 目标股票或标的映射。"
            "缺失项: market_coverage"
        )
    lines = [f"标的池共 {target_count} 个启用目标; 以下按 {bar} 口径解释最近窗口。"]
    if sessions:
        last = sessions[-1]
        state = "交易日" if last.get("is_session") else "非交易日/休市"
        lines.append(
            f"最近一个日历日 {last.get('trading_date')} 为{state}; "
            f"常规时段 {last.get('regular_start')} 至 {last.get('regular_end')}。"
        )
    for block in coverage:
        summary = block.get("summary") or {}
        lines.append(
            f"{block.get('inst_id')}: 应到 {summary.get('expected')} 根, "
            f"实到 {summary.get('actual')} 根, 缺失 {summary.get('missing')} 根, "
            f"覆盖率 {summary.get('ratio')}。"
        )
    return " ".join(lines)


def relations_citations(
    *,
    target_id: int,
    snapshot: dict[str, Any],
    edges: list[dict[str, Any]],
    max_items: int,
) -> list[dict[str, Any]]:
    source = relations_source(target_id)
    items: list[dict[str, Any]] = [
        citation(
            "relation_snapshot",
            source,
            snapshot_id=snapshot.get("id"),
            target_id=target_id,
            as_of=snapshot.get("as_of"),
            window_bars=snapshot.get("window_bars"),
            method=snapshot.get("method"),
            price_basis=snapshot.get("price_basis"),
            sample_size=snapshot.get("sample_size"),
        )
    ]
    for edge in edges[:max_items]:
        items.append(
            citation(
                "relation_edge",
                source,
                snapshot_id=snapshot.get("id"),
                instrument_id=edge.get("counterparty_inst_id"),
                coefficient=edge.get("coefficient"),
                best_lag=edge.get("best_lag"),
                rank=edge.get("rank"),
            )
        )
    return items


def relation_extremes(edges: list[dict[str, Any]]) -> tuple[dict | None, dict | None]:
    positive = [row for row in edges if _as_float(row.get("coefficient")) > 0]
    negative = [row for row in edges if _as_float(row.get("coefficient")) < 0]
    best_positive = max(positive, key=lambda row: _as_float(row.get("coefficient")), default=None)
    best_negative = min(negative, key=lambda row: _as_float(row.get("coefficient")), default=None)
    return best_positive, best_negative


def relations_summary(
    *,
    target_id: int,
    snapshot: dict[str, Any],
    edges: list[dict[str, Any]],
    significant_changes: int,
) -> str:
    if not edges:
        return f"数据不足: 目标 {target_id} 的关系快照没有显著边。缺失项: relation_edges"
    best_positive, best_negative = relation_extremes(edges)
    parts = [
        f"目标 {target_id} 最近快照 ({snapshot.get('as_of')}, "
        f"窗口 {snapshot.get('window_bars')} 根, {snapshot.get('method')}/"
        f"{snapshot.get('price_basis')}) 共 {len(edges)} 条显著边"
        f" (样本 {snapshot.get('sample_size')}) 。"
    ]
    if best_positive is not None:
        parts.append(
            f"最强正相关为 {best_positive.get('counterparty_inst_id')}, "
            f"系数 {best_positive.get('coefficient')}, 最优滞后 {best_positive.get('best_lag')}。"
        )
    if best_negative is not None:
        parts.append(
            f"最强负相关为 {best_negative.get('counterparty_inst_id')}, "
            f"系数 {best_negative.get('coefficient')}, 最优滞后 {best_negative.get('best_lag')}。"
        )
    parts.append(f"显著变化 {significant_changes} 条。")
    return " ".join(parts)


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "coverage_source",
    "market_citations",
    "market_summary",
    "relation_extremes",
    "relations_citations",
    "relations_source",
    "relations_summary",
    "session_source",
]

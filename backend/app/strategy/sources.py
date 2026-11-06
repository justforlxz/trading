"""策略生成的数据来源：把机会批次或目标关系解析成候选腿（只读 IO）。

这里只读 `opportunity`/`research`/`market` 的既有数据，不调用它们的 service，
也不改写任何行情。任何指标缺失都写进 `exclusions` 并排除该标的，绝不补零或伪造
价格；因此生成结果对同一份数据是确定的。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.market.models import Instrument
from app.opportunity.models import Opportunity, OpportunityRun
from app.research.models import (
    MarketSnapshot,
    RelationEdge,
    RelationSnapshot,
    RelativeStrengthSnapshot,
    TargetSymbol,
)
from app.strategy.core.builder import LegCandidate
from app.strategy.core.constraints import ConstraintViolation

MISSING_SNAPSHOT = "missing market snapshot (no candles or insufficient samples)"
DROPPED_BY_MAX_LEGS = "candidate dropped: max_legs limit reached"


@dataclass(frozen=True)
class SourceResolution:
    """一次生成的输入：候选腿、来源溯源信息、被排除的标的与原因、数据窗口。"""

    candidates: list[LegCandidate]
    source: dict[str, Any]
    exclusions: list[dict[str, Any]]
    window_bars: int


def _cap_candidates(
    candidates: list[LegCandidate], *, limit: int, exclusions: list[dict[str, Any]]
) -> list[LegCandidate]:
    """超出腿数上限的候选也要留下排除原因，不做静默丢弃。"""

    for candidate in candidates[limit:]:
        exclusions.append(
            {
                "instrument_id": candidate.instrument_id,
                "inst_id": candidate.inst_id,
                "reason": DROPPED_BY_MAX_LEGS,
            }
        )
    return candidates[:limit]


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _not_found(code: str, message: str, details: dict[str, Any]) -> ConstraintViolation:
    return ConstraintViolation(code, message, status_code=404, details=details)


def _no_data(message: str, details: dict[str, Any]) -> ConstraintViolation:
    return ConstraintViolation("strategy_no_source_data", message, status_code=422, details=details)


async def _latest_market_snapshots(
    session: AsyncSession, instrument_ids: list[int]
) -> dict[int, MarketSnapshot]:
    """每个标的取最新一条 `research.market_snapshot`；没有快照的标的不在返回值里。"""

    if not instrument_ids:
        return {}
    latest = (
        select(
            MarketSnapshot.instrument_id.label("instrument_id"),
            func.max(MarketSnapshot.as_of).label("as_of"),
        )
        .where(MarketSnapshot.instrument_id.in_(instrument_ids))
        .group_by(MarketSnapshot.instrument_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(MarketSnapshot).join(
                latest,
                (MarketSnapshot.instrument_id == latest.c.instrument_id)
                & (MarketSnapshot.as_of == latest.c.as_of),
            )
        )
    ).scalars()
    return {row.instrument_id: row for row in rows}


async def _latest_relative_strength(
    session: AsyncSession, *, target_id: int, counterparty_ids: list[int]
) -> dict[int, tuple[float | None, float | None]]:
    """每个对手方取最新相对强弱快照；返回 `counterparty_id -> (rs_ratio, rs_momentum)`。"""

    if not counterparty_ids:
        return {}
    rows = (
        await session.execute(
            select(
                RelativeStrengthSnapshot.counterparty_id,
                RelativeStrengthSnapshot.rs_ratio,
                RelativeStrengthSnapshot.rs_momentum,
            )
            .where(
                RelativeStrengthSnapshot.target_id == target_id,
                RelativeStrengthSnapshot.counterparty_id.in_(counterparty_ids),
            )
            .order_by(RelativeStrengthSnapshot.as_of.desc(), RelativeStrengthSnapshot.id.desc())
        )
    ).all()
    latest: dict[int, tuple[float | None, float | None]] = {}
    for counterparty_id, rs_ratio, rs_momentum in rows:
        latest.setdefault(counterparty_id, (_number(rs_ratio), _number(rs_momentum)))
    return latest


async def resolve_opportunity(
    session: AsyncSession, *, opportunity_id: int, kind: str, settings: Settings
) -> SourceResolution:
    """机会驱动：方向性取簇成员，相对价值取配对双腿。"""

    opportunity = await session.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise _not_found(
            "OPPORTUNITY_NOT_FOUND",
            f"opportunity {opportunity_id} not found",
            {"opportunity_id": opportunity_id},
        )
    run = await session.get(OpportunityRun, opportunity.run_id)
    window = settings.opportunity_lookback_bars
    if run is not None and isinstance(run.params, dict):
        window = int(run.params.get("lookback_bars", window))

    evidence: dict[str, Any] = dict(opportunity.evidence or {})
    source = {
        "type": "opportunity",
        "opportunity_id": opportunity.id,
        "run_id": opportunity.run_id,
        "cluster_label": evidence.get("cluster"),
        "kind": opportunity.kind,
        "direction": opportunity.direction,
    }
    metrics_window = {"window": window}

    if kind == "relative_value":
        long_id = evidence.get("long_instrument_id")
        short_id = evidence.get("short_instrument_id")
        long_inst = evidence.get("long_inst_id")
        short_inst = evidence.get("short_inst_id")
        if long_id is None or short_id is None or not long_inst or not short_inst:
            raise _no_data(
                f"opportunity {opportunity_id} has no pair legs to build a strategy",
                {"opportunity_id": opportunity_id, "evidence_keys": sorted(evidence)},
            )
        shared = {
            "spread_z": evidence.get("spread_z"),
            "correlation": evidence.get("correlation"),
            "overlap_bars": evidence.get("overlap_bars"),
            **metrics_window,
        }
        return SourceResolution(
            candidates=[
                LegCandidate(
                    instrument_id=int(long_id),
                    inst_id=str(long_inst),
                    side="long",
                    metrics=dict(shared),
                ),
                LegCandidate(
                    instrument_id=int(short_id),
                    inst_id=str(short_inst),
                    side="short",
                    metrics=dict(shared),
                ),
            ],
            source=source,
            exclusions=[],
            window_bars=window,
        )

    members = evidence.get("members") or []
    direction = opportunity.direction
    if direction not in ("long", "short"):
        raise _no_data(
            f"opportunity {opportunity_id} has no directional signal",
            {"opportunity_id": opportunity_id, "direction": direction},
        )
    candidates = [
        LegCandidate(
            instrument_id=int(member["instrument_id"]),
            inst_id=str(member["inst_id"]),
            side=direction,
            symbol=member.get("symbol"),
            metrics={
                "ret_1d": member.get("ret_1d"),
                "ret_5d": member.get("ret_5d"),
                "ret_20d": member.get("ret_20d"),
                "vol_20d": member.get("vol_20d"),
                "correlation": member.get("correlation"),
                **metrics_window,
            },
        )
        for member in members
        if member.get("instrument_id") is not None and member.get("inst_id")
    ]
    if not candidates:
        raise _no_data(
            f"opportunity {opportunity_id} has no member legs",
            {"opportunity_id": opportunity_id},
        )
    exclusions: list[dict[str, Any]] = []
    return SourceResolution(
        candidates=_cap_candidates(
            candidates, limit=settings.strategy_max_legs, exclusions=exclusions
        ),
        source=source,
        exclusions=exclusions,
        window_bars=window,
    )


async def resolve_target(
    session: AsyncSession, *, target_id: int, kind: str, settings: Settings
) -> SourceResolution:
    """目标驱动：用最新关系快照的对手方构建组合，腿指标全部来自 S4 快照。"""

    target = await session.get(TargetSymbol, target_id)
    if target is None:
        raise _not_found(
            "TARGET_NOT_FOUND", f"target {target_id} not found", {"target_id": target_id}
        )
    if target.instrument_id is None:
        raise _no_data(
            f"target {target_id} has no resolved instrument",
            {"target_id": target_id, "reason": "target instrument is not resolved"},
        )

    snapshot = (
        await session.execute(
            select(RelationSnapshot)
            .where(RelationSnapshot.target_id == target_id)
            .order_by(RelationSnapshot.as_of.desc(), RelationSnapshot.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if snapshot is None:
        raise _no_data(
            f"target {target_id} has no relation snapshot",
            {"target_id": target_id, "reason": "no relation snapshot"},
        )

    edges = (
        await session.execute(
            select(RelationEdge, Instrument.inst_id, Instrument.uly)
            .join(Instrument, Instrument.id == RelationEdge.counterparty_id)
            .where(RelationEdge.snapshot_id == snapshot.id)
            .order_by(
                func.abs(RelationEdge.coefficient).desc(),
                RelationEdge.rank.asc(),
                RelationEdge.id.asc(),
            )
        )
    ).all()
    if not edges:
        raise _no_data(
            f"target {target_id} relation snapshot has no edges",
            {"target_id": target_id, "snapshot_id": snapshot.id},
        )

    instrument_ids = [target.instrument_id, *(edge.counterparty_id for edge, _, _ in edges)]
    snaps = await _latest_market_snapshots(session, instrument_ids)
    anchor_inst = (
        await session.execute(
            select(Instrument.inst_id, Instrument.uly).where(Instrument.id == target.instrument_id)
        )
    ).one()

    source = {
        "type": "target",
        "target_id": target_id,
        "relation_snapshot_id": snapshot.id,
        "as_of": snapshot.as_of.isoformat(),
        "method": snapshot.method,
        "price_basis": snapshot.price_basis,
        "window_bars": snapshot.window_bars,
    }
    window = int(snapshot.window_bars)
    exclusions: list[dict[str, Any]] = []

    def leg_metrics(row: MarketSnapshot | None, *, coefficient: Any, peer: float | None) -> dict:
        return {
            "coefficient": coefficient,
            "stability": None,
            "ret_5d": None if row is None else row.ret_5d,
            "ret_20d": None if row is None else row.ret_20d,
            "vol_20d": None if row is None else row.vol_20d,
            "peer_ret_5d": peer,
            "window": window,
        }

    if kind == "relative_value":
        anchor_row = snaps.get(target.instrument_id)
        anchor_ret = None if anchor_row is None else _number(anchor_row.ret_5d)
        peer_ids = [edge.counterparty_id for edge, _, _ in edges]
        relative = await _latest_relative_strength(
            session, target_id=target_id, counterparty_ids=peer_ids
        )
        for edge, inst_id, _uly in edges:
            peer_row = snaps.get(edge.counterparty_id)
            if peer_row is None:
                exclusions.append(
                    {
                        "instrument_id": edge.counterparty_id,
                        "inst_id": inst_id,
                        "reason": MISSING_SNAPSHOT,
                    }
                )
                continue
            rs_ratio, rs_momentum = relative.get(edge.counterparty_id, (None, None))
            peer_ret = _number(peer_row.ret_5d)
            if rs_ratio is not None:
                target_strong = rs_ratio >= 1.0
            elif anchor_ret is not None and peer_ret is not None:
                target_strong = anchor_ret >= peer_ret
            else:
                target_strong = True
            target_side = "long" if target_strong else "short"
            peer_side = "short" if target_strong else "long"
            edge_metrics = {
                "coefficient": edge.coefficient,
                "stability": edge.stability,
                "best_lag": edge.best_lag,
                "rs_ratio": rs_ratio,
                "rs_momentum": rs_momentum,
                "window": window,
            }
            candidates = [
                LegCandidate(
                    instrument_id=target.instrument_id,
                    inst_id=anchor_inst.inst_id,
                    side=target_side,
                    metrics={
                        **edge_metrics,
                        "ret_5d": anchor_ret,
                        "peer_ret_5d": peer_ret,
                    },
                ),
                LegCandidate(
                    instrument_id=edge.counterparty_id,
                    inst_id=inst_id,
                    side=peer_side,
                    metrics={
                        **edge_metrics,
                        "ret_5d": peer_ret,
                        "peer_ret_5d": anchor_ret,
                    },
                ),
            ]
            return SourceResolution(
                candidates=candidates,
                source=source,
                exclusions=exclusions,
                window_bars=window,
            )
        raise _no_data(
            f"target {target_id} has no counterparty with market data",
            {"target_id": target_id, "snapshot_id": snapshot.id, "exclusions": exclusions},
        )

    # 方向性：以目标自身 5 日收益定方向，同向布局正相关对手方。
    anchor_row = snaps.get(target.instrument_id)
    anchor_ret = None if anchor_row is None else _number(anchor_row.ret_5d)
    if anchor_ret is None:
        exclusions.append(
            {
                "instrument_id": target.instrument_id,
                "inst_id": anchor_inst.inst_id,
                "reason": MISSING_SNAPSHOT,
            }
        )

    peers: list[tuple[Any, str, MarketSnapshot]] = []
    for edge, inst_id, _uly in edges:
        if _number(edge.coefficient) is None or _number(edge.coefficient) <= 0:
            continue
        peer_row = snaps.get(edge.counterparty_id)
        if peer_row is None:
            exclusions.append(
                {
                    "instrument_id": edge.counterparty_id,
                    "inst_id": inst_id,
                    "reason": MISSING_SNAPSHOT,
                }
            )
            continue
        peers.append((edge, inst_id, peer_row))

    peer_returns = [
        value for _edge, _inst, row in peers if (value := _number(row.ret_5d)) is not None
    ]
    if anchor_ret is not None:
        direction = "long" if anchor_ret > 0 else "short"
    elif peer_returns:
        direction = "long" if sum(peer_returns) / len(peer_returns) > 0 else "short"
    else:
        raise _no_data(
            f"target {target_id} has no return data to determine direction",
            {"target_id": target_id, "exclusions": exclusions},
        )

    candidates: list[LegCandidate] = []
    if anchor_ret is not None:
        top_edge = peers[0][0] if peers else edges[0][0]
        candidates.append(
            LegCandidate(
                instrument_id=target.instrument_id,
                inst_id=anchor_inst.inst_id,
                side=direction,
                metrics=leg_metrics(
                    anchor_row,
                    coefficient=top_edge.coefficient,
                    peer=(_number(peers[0][2].ret_5d) if peers else None),
                ),
            )
        )
    for edge, inst_id, row in peers:
        candidates.append(
            LegCandidate(
                instrument_id=edge.counterparty_id,
                inst_id=inst_id,
                side=direction,
                metrics={
                    **leg_metrics(row, coefficient=edge.coefficient, peer=anchor_ret),
                    "stability": edge.stability,
                    "best_lag": edge.best_lag,
                },
            )
        )
    if len(candidates) < settings.strategy_min_legs:
        raise _no_data(
            f"target {target_id} has too few instruments with market data",
            {
                "target_id": target_id,
                "candidates": len(candidates),
                "min_legs": settings.strategy_min_legs,
                "exclusions": exclusions,
            },
        )
    return SourceResolution(
        candidates=_cap_candidates(
            candidates, limit=settings.strategy_max_legs, exclusions=exclusions
        ),
        source=source,
        exclusions=exclusions,
        window_bars=window,
    )


__all__ = ["SourceResolution", "resolve_opportunity", "resolve_target"]

"""`/api/v1/opportunities/*` 与 `/api/v1/market/snapshot`（P1-13）。

决策计算全部在 `app.analysis.core`；本模块只做参数校验、查询编排与响应组装。
扫描本身是后台任务：`POST /opportunities/scan` 走 `jobs.create_run` + `dispatch`，
进程内不做重活。

`/market/snapshot` 也放在这里：`research.market_snapshot` 是扫描的产物，
只有本域读写它，因此不把这条端点塞进 market 模块造成跨域读写。
"""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.core.opportunities import assert_explainable, market_breadth
from app.api.errors import ApiError
from app.api.v1.deps import dispatch, session_dep
from app.config import get_settings
from app.jobs import tasks
from app.jobs.runs import create_run
from app.market.core.calendar import session_phase
from app.market.models import Instrument
from app.opportunity.models import (
    AssetCluster,
    ClusterMember,
    Opportunity,
    OpportunityRun,
)
from app.opportunity.scanner import merge_params, params_from_settings
from app.opportunity.schemas import OpportunityDirection, OpportunityKind, ScanRequest
from app.research.models import MarketSnapshot

router = APIRouter(prefix="/opportunities", tags=["opportunity"])
cluster_router = APIRouter(prefix="/clusters", tags=["opportunity"])
market_router = APIRouter(prefix="/market", tags=["market"])

SessionDep = Annotated[AsyncSession, Depends(session_dep)]

MAX_LIMIT = 200
DEFAULT_LIMIT = 50


def _dec(value: Any | None) -> str | None:
    """Decimal 一律以字符串返回，避免前端 JSON 解析丢精度。"""

    return None if value is None else str(value)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _symbol(inst_id: str, uly: str | None) -> str:
    return (uly or inst_id.split("-")[0]).upper()


def _parse_as_of(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ApiError(
            "INVALID_AS_OF", f"as_of must be ISO-8601, got {value!r}", status_code=422
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ApiError(
            "INVALID_AS_OF", "as_of must be timezone-aware ISO-8601 (e.g. ...Z)", status_code=422
        )
    return parsed


def _encode_cursor(score: Decimal, row_id: int) -> str:
    raw = f"{score}:{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(value: str) -> tuple[Decimal, int]:
    try:
        decoded = base64.urlsafe_b64decode(value.encode()).decode()
        score_text, id_text = decoded.split(":", 1)
        return Decimal(score_text), int(id_text)
    except (ValueError, UnicodeDecodeError, binascii.Error) as error:
        raise ApiError(
            "INVALID_CURSOR", "cursor is not a valid scan cursor", status_code=422
        ) from error


def opportunity_payload(row: Opportunity, instrument: Instrument | None) -> dict[str, Any]:
    """单条机会；`reasons` 与 `evidence` 原样透出，绝不返回裸分数。

    构造时再校验一次可解释性：即使库里被人为写入残缺记录，响应也不会
    悄悄变成一条只有分数的「黑箱」机会。
    """

    assert_explainable(row.reasons or [], row.evidence or {})
    return {
        "id": row.id,
        "run_id": row.run_id,
        "kind": row.kind,
        "direction": row.direction,
        "score": _dec(row.score),
        "horizon": row.horizon,
        "reasons": row.reasons,
        "evidence": row.evidence,
        "primary_instrument_id": row.primary_instrument_id,
        "primary_inst_id": None if instrument is None else instrument.inst_id,
        "primary_symbol": None
        if instrument is None
        else _symbol(instrument.inst_id, instrument.uly),
        "created_at": _iso(row.created_at),
    }


def run_payload(row: OpportunityRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_key": row.run_key,
        "as_of": _iso(row.as_of),
        "universe_size": row.universe_size,
        "status": row.status,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "error": row.error,
        "params": row.params,
        "counts": row.counts,
    }


@router.post("/scan", status_code=status.HTTP_202_ACCEPTED)
async def trigger_scan(
    payload: ScanRequest,
    session: SessionDep,
    response: Response,
) -> dict[str, Any]:
    """提交一次全市场扫描；同一 `(as_of, universe, params)` 命中既有批次时返回 200。"""

    overrides = None if payload.params is None else payload.params.overrides()
    effective = merge_params(params_from_settings(get_settings()), overrides)
    run, created = await create_run(
        session,
        job_name=tasks.SCAN_OPPORTUNITIES,
        payload={
            "as_of": _iso(payload.as_of),
            "universe": sorted(payload.universe) if payload.universe else None,
            "params": effective,
        },
    )
    body = {
        "job_id": run.id,
        "status": run.status if created else "skipped",
        "job_name": run.job_name,
        "job_key": run.job_key,
    }
    if not created:
        response.status_code = status.HTTP_200_OK
        return body
    await dispatch(
        tasks.SCAN_OPPORTUNITIES,
        run_id=run.id,
        as_of=payload.as_of,
        universe=payload.universe,
        params=overrides,
    )
    response.headers["Location"] = f"/api/v1/ops/job-runs/{run.id}"
    return body


@router.get("/runs")
async def list_runs(
    session: SessionDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    run_key: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: int | None = None,
) -> dict[str, Any]:
    """批次列表，按 id 倒序；`next_cursor` 为空表示到底。"""

    stmt = select(OpportunityRun).order_by(OpportunityRun.id.desc())
    if status_filter:
        stmt = stmt.where(OpportunityRun.status == status_filter)
    if run_key:
        stmt = stmt.where(OpportunityRun.run_key == run_key)
    if cursor is not None:
        stmt = stmt.where(OpportunityRun.id < cursor)
    rows = (await session.scalars(stmt.limit(limit + 1))).all()
    next_cursor = rows[limit].id if len(rows) > limit else None
    return {
        "items": [run_payload(row) for row in rows[:limit]],
        "next_cursor": next_cursor,
    }


@router.get("/runs/{run_id}")
async def get_run(run_id: int, session: SessionDep) -> dict[str, Any]:
    row = await session.scalar(select(OpportunityRun).where(OpportunityRun.id == run_id))
    if row is None:
        raise ApiError("RUN_NOT_FOUND", f"unknown run_id: {run_id}", status_code=404)
    return run_payload(row)


@router.get("")
async def list_opportunities(
    session: SessionDep,
    run_id: int | None = None,
    kind: OpportunityKind | None = None,
    direction: OpportunityDirection | None = None,
    min_score: float | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
) -> dict[str, Any]:
    """按分数倒序返回机会；默认取最新批次，每条都带 `reasons` 与 `evidence`。"""

    if run_id is None:
        run_id = await session.scalar(
            select(func.max(OpportunityRun.id)).where(OpportunityRun.status.in_(["ok", "partial"]))
        )
        if run_id is None:
            return {"items": [], "next_cursor": None, "run_id": None}

    stmt = (
        select(Opportunity, Instrument)
        .join(Instrument, Instrument.id == Opportunity.primary_instrument_id)
        .where(Opportunity.run_id == run_id)
        .order_by(Opportunity.score.desc(), Opportunity.id.desc())
    )
    if kind is not None:
        stmt = stmt.where(Opportunity.kind == kind)
    if direction is not None:
        stmt = stmt.where(Opportunity.direction == direction)
    if min_score is not None:
        stmt = stmt.where(Opportunity.score >= Decimal(str(min_score)))
    if cursor is not None:
        last_score, last_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Opportunity.score < last_score,
                and_(Opportunity.score == last_score, Opportunity.id < last_id),
            )
        )
    rows = (await session.execute(stmt.limit(limit + 1))).all()
    visible = rows[:limit]
    next_cursor = (
        _encode_cursor(visible[-1][0].score, visible[-1][0].id)
        if len(rows) > limit and visible
        else None
    )
    return {
        "run_id": run_id,
        "items": [opportunity_payload(row, instrument) for row, instrument in visible],
        "next_cursor": next_cursor,
    }


@router.get("/{opportunity_id}")
async def get_opportunity(opportunity_id: int, session: SessionDep) -> dict[str, Any]:
    row = (
        await session.execute(
            select(Opportunity, Instrument)
            .join(Instrument, Instrument.id == Opportunity.primary_instrument_id)
            .where(Opportunity.id == opportunity_id)
        )
    ).first()
    if row is None:
        raise ApiError(
            "OPPORTUNITY_NOT_FOUND",
            f"unknown opportunity_id: {opportunity_id}",
            status_code=404,
        )
    opportunity, instrument = row
    payload = opportunity_payload(opportunity, instrument)
    payload["members"] = opportunity.evidence.get("members", []) if opportunity.evidence else []
    return payload


@cluster_router.get("")
async def list_clusters(
    session: SessionDep,
    run_id: int | None = None,
) -> dict[str, Any]:
    """某个批次的资产簇及嵌套成员；`run_id` 缺省取最新成功批次。"""

    if run_id is None:
        run_id = await session.scalar(
            select(func.max(OpportunityRun.id)).where(OpportunityRun.status.in_(["ok", "partial"]))
        )
        if run_id is None:
            return {"run_id": None, "items": []}
    clusters = (
        await session.scalars(
            select(AssetCluster)
            .where(AssetCluster.run_id == run_id)
            .order_by(AssetCluster.size.desc(), AssetCluster.label)
        )
    ).all()
    if not clusters:
        return {"run_id": run_id, "items": []}
    members = (
        await session.execute(
            select(ClusterMember, Instrument)
            .join(Instrument, Instrument.id == ClusterMember.instrument_id)
            .where(ClusterMember.cluster_id.in_([cluster.id for cluster in clusters]))
            .order_by(ClusterMember.distance)
        )
    ).all()
    grouped: dict[int, list[dict[str, Any]]] = {}
    for member, instrument in members:
        grouped.setdefault(member.cluster_id, []).append(
            {
                "instrument_id": member.instrument_id,
                "inst_id": instrument.inst_id,
                "symbol": _symbol(instrument.inst_id, instrument.uly),
                "distance": _dec(member.distance),
                "weight": _dec(member.weight),
            }
        )
    return {
        "run_id": run_id,
        "items": [
            {
                "id": cluster.id,
                "run_id": cluster.run_id,
                "label": cluster.label,
                "method": cluster.method,
                "silhouette": _dec(cluster.silhouette),
                "size": cluster.size,
                "centroid": cluster.centroid,
                "members": grouped.get(cluster.id, []),
            }
            for cluster in clusters
        ],
    }


@market_router.get("/snapshot")
async def market_snapshot(
    session: SessionDep,
    as_of: str | None = None,
) -> dict[str, Any]:
    """全市场特征截面（驾驶舱数据源）；`as_of` 缺省取最新一次扫描的截面。"""

    moment = (
        _parse_as_of(as_of)
        if as_of
        else await session.scalar(select(func.max(MarketSnapshot.as_of)))
    )
    if moment is None:
        return {
            "as_of": None,
            "items": [],
            "count": 0,
            "breadth": None,
            "session": session_phase(datetime.now(UTC)),
        }
    rows = (
        await session.execute(
            select(MarketSnapshot, Instrument)
            .join(Instrument, Instrument.id == MarketSnapshot.instrument_id)
            .where(MarketSnapshot.as_of == moment)
            .order_by(Instrument.inst_id)
        )
    ).all()
    items = [
        {
            "instrument_id": snapshot.instrument_id,
            "inst_id": instrument.inst_id,
            "symbol": _symbol(instrument.inst_id, instrument.uly),
            "asset_class": instrument.asset_class,
            "ret_1d": _dec(snapshot.ret_1d),
            "ret_5d": _dec(snapshot.ret_5d),
            "ret_20d": _dec(snapshot.ret_20d),
            "vol_20d": _dec(snapshot.vol_20d),
            "atr_14": _dec(snapshot.atr_14),
            "volume_z": _dec(snapshot.volume_z),
            "high_20d": _dec(snapshot.high_20d),
            "low_20d": _dec(snapshot.low_20d),
            "extras": snapshot.extras,
        }
        for snapshot, instrument in rows
    ]
    returns = [float(snapshot.ret_1d) for snapshot, _ in rows if snapshot.ret_1d is not None]
    return {
        "as_of": _iso(moment),
        "count": len(items),
        "breadth": market_breadth(returns),
        # 美股时段由市场日历纯函数给出，前端只负责展示，不自己算时区与窗口。
        "session": session_phase(datetime.now(UTC)),
        "items": items,
    }


__all__ = [
    "MAX_LIMIT",
    "cluster_router",
    "market_router",
    "opportunity_payload",
    "router",
    "run_payload",
]

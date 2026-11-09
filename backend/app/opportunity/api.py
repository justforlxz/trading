"""`/api/v1/opportunities/*` 与 `/api/v1/market/snapshot`（P1-13）。

决策计算全部在 `app.analysis.core`；本模块只做参数校验、查询编排与响应组装。
只读查询与序列化在 `app.opportunity.query`，与 MCP 共用同一份实现。
扫描本身是后台任务：`POST /opportunities/scan` 走 `jobs.create_run` + `dispatch`，
进程内不做重活。

`/market/snapshot` 也放在这里：`research.market_snapshot` 是扫描的产物，
只有本域读写它，因此不把这条端点塞进 market 模块造成跨域读写。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.v1.deps import dispatch, session_dep
from app.config import get_settings
from app.jobs import tasks
from app.jobs.runs import create_run
from app.market.models import Instrument
from app.opportunity.models import AssetCluster, ClusterMember, OpportunityRun
from app.opportunity.query import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    InvalidCursor,
    get_opportunity_view,
    iso_text,
    list_opportunities_view,
    market_snapshot_view,
    opportunity_payload,
    run_payload,
    symbol_text,
)
from app.opportunity.query import dec_text as _dec
from app.opportunity.scanner import merge_params, params_from_settings
from app.opportunity.schemas import OpportunityDirection, OpportunityKind, ScanRequest

router = APIRouter(prefix="/opportunities", tags=["opportunity"])
cluster_router = APIRouter(prefix="/clusters", tags=["opportunity"])
market_router = APIRouter(prefix="/market", tags=["market"])

SessionDep = Annotated[AsyncSession, Depends(session_dep)]


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
            "as_of": iso_text(payload.as_of),
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

    try:
        return await list_opportunities_view(
            session,
            run_id=run_id,
            kind=None if kind is None else kind.value,
            direction=None if direction is None else direction.value,
            min_score=min_score,
            limit=limit,
            cursor=cursor,
        )
    except InvalidCursor as error:
        raise ApiError("INVALID_CURSOR", str(error), status_code=422) from error


@router.get("/{opportunity_id}")
async def get_opportunity(opportunity_id: int, session: SessionDep) -> dict[str, Any]:
    payload = await get_opportunity_view(session, opportunity_id)
    if payload is None:
        raise ApiError(
            "OPPORTUNITY_NOT_FOUND",
            f"unknown opportunity_id: {opportunity_id}",
            status_code=404,
        )
    return payload


@cluster_router.get("")
async def list_clusters(
    session: SessionDep,
    run_id: int | None = None,
) -> dict[str, Any]:
    """某个批次的资产簇及嵌套成员；`run_id` 缺省取最新成功批次。"""

    if run_id is None:
        run_id = await session.scalar(
            select(OpportunityRun.id)
            .where(OpportunityRun.status.in_(["ok", "partial"]))
            .order_by(OpportunityRun.id.desc())
            .limit(1)
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
                "symbol": symbol_text(instrument.inst_id, instrument.uly),
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
async def market_snapshot(session: SessionDep, as_of: str | None = None) -> dict[str, Any]:
    """全市场特征截面（驾驶舱数据源）；`as_of` 缺省取最新一次扫描的截面。"""

    moment = _parse_as_of(as_of) if as_of else None
    return await market_snapshot_view(session, as_of=moment)


__all__ = [
    "MAX_LIMIT",
    "cluster_router",
    "market_router",
    "opportunity_payload",
    "router",
    "run_payload",
]

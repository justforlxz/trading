"""`/api/v1/targets/*`：目标股票 CRUD、关系快照与相对强弱（P1-06 ~ P1-09）。

决策计算全部在 `app.analysis.core`，本模块只做校验、编排与响应组装；
重算走 `jobs.create_run` + `dispatch` 的既有后台任务通道，不在 API 进程里算重活。
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.v1.deps import dispatch, session_dep
from app.api.v1.research_schemas import RecomputeRequest, TargetCreate, TargetUpdate
from app.config import get_settings
from app.jobs import tasks
from app.jobs.runs import create_run
from app.market.models import Instrument
from app.research import relations as relation_service
from app.research import relative_strength as relative_strength_service
from app.research import targets as target_service
from app.research.models import TargetSymbol

router = APIRouter(prefix="/targets", tags=["research"])

SessionDep = Annotated[AsyncSession, Depends(session_dep)]


def target_payload(row: TargetSymbol) -> dict[str, Any]:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "exchange": row.exchange,
        "display_name": row.display_name,
        "note": row.note,
        "instrument_id": row.instrument_id,
        "enabled": row.enabled,
        "created_at": row.created_at.isoformat(),
    }


async def _require_target(session: AsyncSession, target_id: int) -> TargetSymbol:
    row = await target_service.get_target(session, target_id)
    if row is None:
        raise ApiError("TARGET_NOT_FOUND", f"unknown target_id: {target_id}", status_code=404)
    return row


async def _require_instrument(session: AsyncSession, inst_id: str) -> Instrument:
    row = await session.scalar(select(Instrument).where(Instrument.inst_id == inst_id))
    if row is None:
        raise ApiError("INSTRUMENT_NOT_FOUND", f"unknown inst_id: {inst_id}", status_code=404)
    return row


@router.get("")
async def list_targets(
    session: SessionDep,
    enabled: bool | None = True,
    limit: int = Query(50, ge=1, le=200),
    cursor: int | None = None,
) -> dict[str, Any]:
    """默认只列启用中的目标（`enabled=true`）；`enabled=false` 只看已软删除的记录。"""

    rows, next_cursor = await target_service.list_targets(
        session, enabled=enabled, limit=limit, cursor=cursor
    )
    return {"items": [target_payload(row) for row in rows], "next_cursor": next_cursor}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_target(
    payload: TargetCreate, session: SessionDep, response: Response
) -> dict[str, Any]:
    """重复添加同一 `(symbol, exchange)` 返回 200 与已存在记录，不产生副本。"""

    result = await target_service.create_target(
        session,
        symbol=payload.symbol,
        exchange=payload.exchange,
        display_name=payload.display_name,
        note=payload.note,
    )
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return target_payload(result.target)


@router.get("/{target_id}")
async def get_target(target_id: int, session: SessionDep) -> dict[str, Any]:
    return target_payload(await _require_target(session, target_id))


@router.patch("/{target_id}")
async def update_target(
    target_id: int, payload: TargetUpdate, session: SessionDep
) -> dict[str, Any]:
    target = await _require_target(session, target_id)
    fields = payload.model_dump(exclude_unset=True)
    updated = await target_service.update_target(
        session,
        target,
        display_name=fields.get("display_name", target.display_name),
        note=fields.get("note", target.note),
    )
    return target_payload(updated)


@router.delete("/{target_id}")
async def delete_target(target_id: int, session: SessionDep) -> dict[str, Any]:
    """软删除：`enabled=false`，行保留，历史快照外键不悬空。"""

    target = await _require_target(session, target_id)
    return target_payload(await target_service.soft_delete_target(session, target))


@router.post("/{target_id}/relations/recompute", status_code=status.HTTP_202_ACCEPTED)
async def recompute_relations(
    target_id: int, payload: RecomputeRequest, session: SessionDep, response: Response
) -> dict[str, Any]:
    """投递关系重算后台任务；相同参数（同一 `run_key`）不重复计算。"""

    await _require_target(session, target_id)
    settings = get_settings()
    job_payload = {
        "target_id": target_id,
        "window_bars": payload.window_bars,
        "method": payload.method,
        "price_basis": payload.price_basis,
        "as_of": payload.as_of,
        "lag_max": settings.relation_lag_max,
        "stability_window": settings.relation_stability_window,
        "change_threshold": settings.relation_change_threshold,
    }
    run, created = await create_run(
        session, job_name=tasks.RECOMPUTE_RELATIONS, payload=job_payload
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
        tasks.RECOMPUTE_RELATIONS,
        run_id=run.id,
        target_id=target_id,
        window_bars=payload.window_bars,
        method=payload.method,
        price_basis=payload.price_basis,
        as_of=payload.as_of,
    )
    response.headers["Location"] = f"/api/v1/ops/job-runs/{run.id}"
    return body


@router.get("/{target_id}/relations")
async def get_relations(
    target_id: int, session: SessionDep, as_of: str | None = None
) -> dict[str, Any]:
    """无 `as_of` 取最新快照；没有快照时返回 `undefined` + 原因，不造空壳系数。"""

    await _require_target(session, target_id)
    moment = None
    if as_of is not None:
        moment = _parse_as_of(as_of)
    snapshot = await relation_service.latest_snapshot(session, target_id, as_of=moment)
    if snapshot is None:
        return {
            "status": relation_service.STATUS_UNDEFINED,
            "reason": "no_snapshot: 尚未计算过关系快照, 先调用 relation recompute",
            "snapshot": None,
            "edges": [],
            "significant_changes": [],
        }
    settings = get_settings()
    return await relation_service.build_relations_payload(
        session, snapshot, threshold=settings.relation_change_threshold
    )


@router.get("/{target_id}/relations/history")
async def relations_history(
    target_id: int, session: SessionDep, limit: int = Query(20, ge=1, le=200)
) -> dict[str, Any]:
    await _require_target(session, target_id)
    settings = get_settings()
    items = await relation_service.list_history(
        session,
        target_id,
        limit=limit,
        threshold=settings.relation_change_threshold,
    )
    return {"target_id": target_id, "items": items}


@router.get("/{target_id}/relative-strength")
async def relative_strength(
    target_id: int,
    session: SessionDep,
    counterparty: str,
    lookback: int = Query(60, ge=2, le=500),
    price_basis: str = Query("okx_close", pattern="^(okx_close|equity_close)$"),
) -> dict[str, Any]:
    """目标 vs 单个对手方的相对强弱；窗口不足时 `defined=false` 且 `reason` 非空。"""

    target = await _require_target(session, target_id)
    instrument = await _require_instrument(session, counterparty)
    return await relative_strength_service.compute_relative_strength(
        session,
        target=target,
        counterparty=instrument,
        lookback=lookback,
        price_basis=price_basis,
    )


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


__all__ = ["router", "target_payload"]

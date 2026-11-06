"""`/api/v1/market/*`：标的、K 线、真实行情、日历、覆盖率与数据质量。"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.v1.deps import dispatch, session_dep
from app.api.v1.market_schemas import BackfillRequest
from app.config import get_settings
from app.jobs import tasks
from app.jobs.runs import create_run
from app.market import candles as candle_service
from app.market import equity as equity_service
from app.market import instruments as instrument_service
from app.market import sessions as session_service
from app.market.core.bars import normalize_bar
from app.market.models import DataQualityIssue, EquityAsset, Instrument
from app.market.sync_status import list_sync_status
from app.ops.quality import list_issues

router = APIRouter(prefix="/market", tags=["market"])

SessionDep = Annotated[AsyncSession, Depends(session_dep)]


def _dec(value: Any) -> str | None:
    return None if value is None else str(value)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def instrument_payload(row: Instrument) -> dict[str, Any]:
    return {
        "inst_id": row.inst_id,
        "inst_family": row.inst_family,
        "uly": row.uly,
        "inst_category": row.inst_category,
        "asset_class": row.asset_class,
        "exchange": row.exchange,
        "ct_val": _dec(row.ct_val),
        "ct_val_ccy": row.ct_val_ccy,
        "lot_sz": _dec(row.lot_sz),
        "min_sz": _dec(row.min_sz),
        "tick_sz": _dec(row.tick_sz),
        "lever": _dec(row.lever),
        "state": row.state,
        "rule_type": row.rule_type,
        "list_time": _iso(row.list_time),
        "source_synced_at": _iso(row.source_synced_at),
    }


def candle_payload(row) -> dict[str, Any]:
    return {
        "inst_id": None,
        "bar": row.bar,
        "open_time": _iso(row.open_time),
        "open": _dec(row.open),
        "high": _dec(row.high),
        "low": _dec(row.low),
        "close": _dec(row.close),
        "vol": _dec(row.vol),
        "vol_ccy": _dec(row.vol_ccy),
        "vol_ccy_quote": _dec(row.vol_ccy_quote),
        "confirm": row.confirm,
        "source": row.source,
    }


@router.get("/instruments")
async def list_instruments(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    asset_class: str | None = None,
    inst_category: int | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    rows, next_cursor = await instrument_service.list_instruments(
        session,
        limit=limit,
        cursor=cursor,
        asset_class=asset_class,
        inst_category=inst_category,
        query=q,
    )
    return {"items": [instrument_payload(row) for row in rows], "next_cursor": next_cursor}


@router.get("/instruments/{inst_id}")
async def get_instrument(inst_id: str, session: SessionDep) -> dict[str, Any]:
    row = await instrument_service.get_instrument(session, inst_id)
    if row is None:
        raise ApiError("INSTRUMENT_NOT_FOUND", f"unknown inst_id: {inst_id}", status_code=404)
    return instrument_payload(row)


@router.post("/sync/instruments", status_code=status.HTTP_202_ACCEPTED)
async def sync_instruments(
    session: SessionDep,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    """登记并投递全量标的同步；同键任务已存在时不重复投递。"""

    payload = {"scope": "all", "idempotency_key": idempotency_key or ""}
    run, created = await create_run(session, job_name=tasks.SYNC_INSTRUMENTS, payload=payload)
    body = {
        "job_id": run.id,
        "status": run.status if created else "skipped",
        "job_name": run.job_name,
        "job_key": run.job_key,
    }
    if not created:
        response.status_code = status.HTTP_200_OK
        return body
    await dispatch(tasks.SYNC_INSTRUMENTS, run_id=run.id)
    response.headers["Location"] = f"/api/v1/ops/job-runs/{run.id}"
    return body


@router.get("/candles")
async def list_candles(
    session: SessionDep,
    inst_id: str,
    bar: str,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(200, ge=1, le=300),
    cursor: datetime | None = None,
) -> dict[str, Any]:
    normalized = _bar_or_400(bar)
    rows, next_cursor = await candle_service.list_candles(
        session,
        inst_id=inst_id,
        bar=normalized,
        start=start,
        end=end,
        limit=limit,
        cursor=cursor,
    )
    items = [{**candle_payload(row), "inst_id": inst_id} for row in rows]
    return {
        "inst_id": inst_id,
        "bar": normalized,
        "items": items,
        "next_cursor": _iso(next_cursor),
    }


@router.post("/backfill", status_code=status.HTTP_202_ACCEPTED)
async def backfill(
    payload: BackfillRequest, session: SessionDep, response: Response
) -> dict[str, Any]:
    instrument = await instrument_service.get_instrument(session, payload.inst_id)
    if instrument is None:
        raise ApiError(
            "INSTRUMENT_NOT_FOUND", f"unknown inst_id: {payload.inst_id}", status_code=404
        )
    run, created = await create_run(
        session,
        job_name=tasks.BACKFILL_CANDLES,
        payload={
            "inst_id": payload.inst_id,
            "bar": payload.bar,
            "start": payload.start,
            "end": payload.end,
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
        tasks.BACKFILL_CANDLES,
        run_id=run.id,
        inst_id=payload.inst_id,
        bar=payload.bar,
        start=payload.start,
        end=payload.end,
    )
    response.headers["Location"] = f"/api/v1/ops/job-runs/{run.id}"
    return body


@router.get("/sessions")
async def list_sessions(
    session: SessionDep,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
) -> dict[str, Any]:
    end = (to or datetime.now(tz=UTC)).date()
    start = (
        from_ or (datetime.combine(end, datetime.min.time(), tzinfo=UTC) - timedelta(days=29))
    ).date()
    # 日历是纯函数规则算出来的，读之前先落库，避免依赖某个后台任务先跑过。
    await session_service.sync_sessions(session, start=start, end=end)
    rows = await session_service.list_sessions(session, start=start, end=end)
    return {
        "venue": "XNYS",
        "from": start.isoformat(),
        "to": end.isoformat(),
        "items": [session_service.session_payload(row) for row in rows],
    }


@router.get("/coverage")
async def coverage(
    session: SessionDep,
    inst_id: str,
    bar: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    normalized = _bar_or_400(bar)
    instrument = await instrument_service.get_instrument(session, inst_id)
    if instrument is None:
        raise ApiError("INSTRUMENT_NOT_FOUND", f"unknown inst_id: {inst_id}", status_code=404)
    moment = end or datetime.now(tz=UTC)
    window_start = start or moment - timedelta(days=30 if normalized == "1d" else 3)
    return await candle_service.coverage(
        session, instrument=instrument, bar=normalized, start=window_start, end=moment
    )


@router.get("/quality-issues")
async def quality_issues(
    session: SessionDep,
    dataset: str | None = None,
    scope_id: str | None = None,
    kind: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: int | None = None,
) -> dict[str, Any]:
    if status_filter not in (None, "open", "resolved"):
        raise ApiError(
            "INVALID_STATUS",
            f"status must be open or resolved, got {status_filter!r}",
            status_code=400,
        )
    rows, next_cursor = await list_issues(
        session,
        dataset=dataset,
        scope_id=scope_id,
        kind=kind,
        status=status_filter,
        limit=limit,
        cursor=cursor,
    )
    return {
        "items": [
            {
                "id": row.id,
                "dataset": row.dataset,
                "scope_id": row.scope_id,
                "kind": row.kind,
                "severity": row.severity,
                "window_start": _iso(row.window_start),
                "window_end": _iso(row.window_end),
                "detail": row.detail,
                "detected_at": _iso(row.detected_at),
                "last_seen_at": _iso(row.last_seen_at),
                "resolved_at": _iso(row.resolved_at),
            }
            for row in rows
        ],
        "next_cursor": next_cursor,
    }


@router.get("/equity-assets")
async def equity_assets(
    session: SessionDep, limit: int = Query(200, ge=1, le=200)
) -> dict[str, Any]:
    statement = select(EquityAsset).order_by(EquityAsset.symbol).limit(limit)
    rows = list(await session.scalars(statement))
    return {"items": [equity_service.asset_payload(row) for row in rows]}


@router.get("/equity-candles")
async def equity_candles(
    session: SessionDep,
    symbol: str,
    interval: str = "1d",
    limit: int = Query(200, ge=1, le=300),
    cursor: datetime | None = None,
) -> dict[str, Any]:
    rows, next_cursor = await equity_service.list_equity_candles(
        session, symbol=symbol, interval=interval, limit=limit, cursor=cursor
    )
    return {
        "symbol": symbol,
        "interval": interval,
        "items": [
            {
                "ts": _iso(row.ts),
                "open": _dec(row.open),
                "high": _dec(row.high),
                "low": _dec(row.low),
                "close": _dec(row.close),
                "volume": _dec(row.volume),
                "session": row.session,
                "source": row.source,
            }
            for row in rows
        ],
        "next_cursor": _iso(next_cursor),
    }


@router.get("/basis")
async def basis(
    session: SessionDep, inst_id: str, limit: int = Query(50, ge=1, le=200)
) -> dict[str, Any]:
    rows = await equity_service.list_basis(session, inst_id=inst_id, limit=limit)
    return {
        "inst_id": inst_id,
        "items": [
            {
                "symbol": row.symbol,
                "ts": _iso(row.ts),
                "okx_price": _dec(row.okx_price),
                "equity_price": _dec(row.equity_price),
                "basis_bps": _dec(row.basis_bps),
                "source": row.source,
            }
            for row in rows
        ],
    }


@router.get("/sync-status")
async def sync_status(session: SessionDep) -> dict[str, Any]:
    """按 source/dataset/scope 聚合最新采集状态，并按各自间隔判定 stale。"""

    settings = get_settings()
    thresholds = {
        "market.instrument": settings.sync_instruments_interval_seconds * 3,
        "market.candle": settings.ingest_candles_interval_seconds * 3,
        "market.equity_candle": settings.sync_equity_interval_seconds * 3,
    }
    items = await list_sync_status(session, stale_after_seconds=thresholds)
    total = await instrument_service.count_instruments(session)
    unresolved = await session.scalar(
        select(func.count())
        .select_from(DataQualityIssue)
        .where(DataQualityIssue.resolved_at.is_(None))
    )
    by_class = await session.execute(
        select(Instrument.asset_class, func.count()).group_by(Instrument.asset_class)
    )
    return {
        "items": items,
        "stale": sum(1 for item in items if item["stale"]),
        "instruments": total,
        "unresolved_issues": int(unresolved or 0),
        "by_asset_class": {name: int(count) for name, count in by_class},
    }


def _bar_or_400(bar: str) -> str:
    try:
        return normalize_bar(bar)
    except ValueError as error:
        raise ApiError("UNSUPPORTED_BAR", str(error), status_code=400) from error


__all__ = ["instrument_payload", "router"]

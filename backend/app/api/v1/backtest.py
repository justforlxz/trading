"""`/api/v1/backtests`：回测提交与报告读取（只做协议编排）。

计算在 `app.backtest` 的纯函数里，落库与排队在 `app.backtest.service` 与
`app.jobs`，本文件只负责请求解析、错误信封与响应组装。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.v1.deps import dispatch, session_dep
from app.backtest import service
from app.backtest.costs import CostModel
from app.backtest.engine import Window
from app.backtest.errors import BacktestError
from app.backtest.models import BacktestEquityPoint, BacktestMetric, BacktestRun, BacktestTrade
from app.jobs import runs as job_runs
from app.jobs import tasks
from app.market.models import Instrument

router = APIRouter(prefix="/backtests", tags=["backtest"])
SessionDep = Annotated[AsyncSession, Depends(session_dep)]

MAX_LIMIT = 2000


class WindowInput(BaseModel):
    start: datetime
    end: datetime
    name: str | None = None
    role: Literal["train", "test", "eval"] = "eval"


class CostModelInput(BaseModel):
    taker_fee_bps: Decimal = Field(default=Decimal(0), ge=0, le=10_000)
    maker_fee_bps: Decimal = Field(default=Decimal(0), ge=0, le=10_000)
    slippage_bps: Decimal = Field(default=Decimal(0), ge=0, le=10_000)
    funding_bps_per_period: Decimal = Field(default=Decimal(0), ge=-10_000, le=10_000)
    funding: bool = True
    fee_role: Literal["taker", "maker"] = "taker"


class ThresholdInput(BaseModel):
    name: str = Field(min_length=1)
    op: Literal[">=", "<=", ">", "<", "=="]
    value: Decimal


class CriteriaInput(BaseModel):
    thresholds: list[ThresholdInput] = Field(default_factory=list)


class CreateBacktestRequest(BaseModel):
    strategy_id: int
    window: WindowInput
    windows: list[WindowInput] = Field(default_factory=list)
    bar: str = "1d"
    initial_capital: Decimal = Field(default=Decimal("100000"), gt=0)
    cost_model: CostModelInput = Field(default_factory=CostModelInput)
    criteria: CriteriaInput | None = None
    annualization_factor: Decimal | None = Field(default=None, gt=0)
    risk_free_rate: Decimal = Decimal(0)
    rebalance: Literal["none", "daily"] = "none"


def _dec(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _fail(exc: BacktestError) -> None:
    raise ApiError(exc.code, exc.message, status_code=exc.status_code, details=exc.details) from exc


def _to_window(item: WindowInput) -> Window:
    return Window(
        name=item.name or "",
        start=item.start,
        end=item.end,
        role=item.role,
    )


def _to_request(payload: CreateBacktestRequest) -> service.BacktestRequest:
    costs = payload.cost_model
    return service.BacktestRequest(
        strategy_id=payload.strategy_id,
        window=_to_window(payload.window),
        windows=tuple(_to_window(item) for item in payload.windows),
        bar=payload.bar,
        initial_capital=payload.initial_capital,
        cost_model=CostModel(
            taker_fee_bps=costs.taker_fee_bps,
            maker_fee_bps=costs.maker_fee_bps,
            slippage_bps=costs.slippage_bps,
            funding_bps_per_period=costs.funding_bps_per_period,
            funding_enabled=costs.funding,
            fee_role=costs.fee_role,
        ),
        thresholds=(
            None
            if payload.criteria is None
            else tuple(item.model_dump() for item in payload.criteria.thresholds)
        ),
        annualization_factor=payload.annualization_factor,
        risk_free_rate=payload.risk_free_rate,
        rebalance=payload.rebalance,
    )


def _run_payload(run: BacktestRun) -> dict[str, Any]:
    params = run.params or {}
    return {
        "id": run.id,
        "run_key": run.run_key,
        "strategy_id": run.strategy_id,
        "strategy_version": run.strategy_version,
        "window": {"start": _iso(run.window_start), "end": _iso(run.window_end)},
        "bar": run.bar,
        "initial_capital": _dec(run.initial_capital),
        "cost_model": run.cost_model,
        "params": params,
        "criteria": params.get("criteria"),
        "funding_assumption": params.get("funding_assumption"),
        "status": run.status,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "error": run.error,
    }


def _metric_payload(row: BacktestMetric) -> dict[str, Any]:
    return {"name": row.name, "value": _dec(row.value), "unit": row.unit}


def _equity_payload(row: BacktestEquityPoint) -> dict[str, Any]:
    return {
        "ts": _iso(row.ts),
        "equity": _dec(row.equity),
        "cash": _dec(row.cash),
        "exposure": _dec(row.exposure),
        "drawdown": _dec(row.drawdown),
    }


def _trade_payload(row: BacktestTrade, inst_id: str | None, symbol: str | None) -> dict[str, Any]:
    return {
        "id": row.id,
        "instrument_id": row.instrument_id,
        "inst_id": inst_id,
        "symbol": symbol,
        "side": row.side,
        "entry_ts": _iso(row.entry_ts),
        "exit_ts": _iso(row.exit_ts),
        "entry_px": _dec(row.entry_px),
        "exit_px": _dec(row.exit_px),
        "qty": _dec(row.qty),
        "gross_pnl": _dec(row.gross_pnl),
        "fees": _dec(row.fees),
        "funding": _dec(row.funding),
        "slippage": _dec(row.slippage),
        "net_pnl": _dec(row.net_pnl),
        "bars_held": row.bars_held,
        "exit_reason": row.exit_reason,
    }


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_backtest(
    payload: CreateBacktestRequest,
    response: Response,
    session: SessionDep,
) -> dict[str, Any]:
    """提交回测；同参数（同 `run_key`）只排队一次。"""

    try:
        run, created = await service.create(session, _to_request(payload))
    except BacktestError as exc:
        _fail(exc)

    job, job_created = await job_runs.create_run(
        session, job_name=tasks.BACKTEST_RUN, payload={"backtest_id": run.id}
    )
    if job_created and run.status != "queued":
        # 已存在的失败运行被 jobs 层重置为 queued：回测行也要同步复位，
        # 否则状态会与 job_run 不一致，且没有轮询会捡起它。
        await service.mark_queued(session, run)
    body = {
        "run_id": run.id,
        "job_id": job.id,
        "status": run.status,
        "run_key": run.run_key,
        "created": created,
        "dispatched": job_created,
    }
    if not job_created:
        response.status_code = status.HTTP_200_OK
        return body

    await dispatch(tasks.BACKTEST_RUN, run_id=job.id, backtest_id=run.id)
    response.headers["Location"] = f"/api/v1/backtests/{run.id}"
    return body


@router.get("/{run_id}")
async def get_backtest(run_id: int, session: SessionDep) -> dict[str, Any]:
    try:
        run = await service.get_run(session, run_id)
    except BacktestError as exc:
        _fail(exc)
    return _run_payload(run)


@router.get("/{run_id}/metrics")
async def get_backtest_metrics(run_id: int, session: SessionDep) -> dict[str, Any]:
    try:
        run = await service.get_run(session, run_id)
        rows = await service.load_metrics(session, run_id)
    except BacktestError as exc:
        _fail(exc)
    return {
        "run_id": run.id,
        "status": run.status,
        "funding_assumption": (run.params or {}).get("funding_assumption"),
        "items": [_metric_payload(row) for row in rows],
    }


@router.get("/{run_id}/equity")
async def get_backtest_equity(
    run_id: int,
    session: SessionDep,
    limit: int = Query(500, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
) -> dict[str, Any]:
    parsed_cursor: datetime | None = None
    if cursor is not None:
        try:
            parsed_cursor = datetime.fromisoformat(cursor.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ApiError("VALIDATION_ERROR", "invalid cursor", status_code=422) from exc
    try:
        rows, next_cursor = await service.load_equity(
            session, run_id, limit=limit, cursor=parsed_cursor
        )
    except BacktestError as exc:
        _fail(exc)
    return {
        "items": [_equity_payload(row) for row in rows],
        "next_cursor": _iso(next_cursor),
    }


@router.get("/{run_id}/trades")
async def get_backtest_trades(
    run_id: int,
    session: SessionDep,
    limit: int = Query(200, ge=1, le=MAX_LIMIT),
    cursor: int | None = None,
) -> dict[str, Any]:
    try:
        rows, next_cursor = await service.load_trades(session, run_id, limit=limit, cursor=cursor)
    except BacktestError as exc:
        _fail(exc)
    ids = {row.instrument_id for row in rows}
    instruments: dict[int, tuple[str, str | None]] = {}
    if ids:
        result = await session.execute(
            select(Instrument.id, Instrument.inst_id, Instrument.uly).where(Instrument.id.in_(ids))
        )
        for instrument_id, inst_id, uly in result.all():
            symbol = (uly or inst_id.split("-")[0]).upper()
            instruments[int(instrument_id)] = (str(inst_id), symbol)
    items = []
    for row in rows:
        inst_id, symbol = instruments.get(row.instrument_id, (None, None))
        items.append(_trade_payload(row, inst_id, symbol))
    return {"items": items, "next_cursor": next_cursor}


__all__ = ["router"]

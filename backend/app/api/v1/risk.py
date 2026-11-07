"""`/api/v1/risk`：风控阈值、状态、事件与资金费率观测（只做协议编排）。

阈值读取与版本、事件去重、评估编排都在 `app.risk.service`，本文件只负责
请求解析、错误信封与响应组装。风控计算全部是 `app.risk.core` 的纯函数。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.okx.client import OkxClient
from app.adapters.okx.rate_limit import UpstreamError, UpstreamUnavailable
from app.adapters.okx.risk import OkxRiskMarketSource
from app.api.errors import ApiError
from app.api.v1.deps import dispatch, session_dep
from app.config import get_settings
from app.jobs import runs as job_runs
from app.jobs import tasks
from app.risk import service
from app.risk.errors import RiskError

router = APIRouter(prefix="/risk", tags=["risk"])
SessionDep = Annotated[AsyncSession, Depends(session_dep)]

MAX_LIMIT = 200


class ThresholdsInput(BaseModel):
    """阈值载荷。字段可缺省，缺字段与非法值都由 service 统一报 ``risk_invalid_threshold``。"""

    max_order_notional: Decimal | None = None
    max_leg_weight: Decimal | None = None
    max_leverage: Decimal | None = None
    max_gross_exposure: Decimal | None = None
    max_net_exposure: Decimal | None = None
    max_instrument_weight: Decimal | None = None
    max_concentration: Decimal | None = None
    drawdown_warn: Decimal | None = None
    drawdown_reduce: Decimal | None = None
    drawdown_close: Decimal | None = None
    funding_rate_threshold: Decimal | None = None
    min_depth_notional: Decimal | None = None


class UpdatePolicyRequest(BaseModel):
    expected_version: int = Field(ge=1)
    updated_by: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    strategy_id: int | None = Field(default=None, ge=1)
    thresholds: ThresholdsInput


class EvaluateRequest(BaseModel):
    strategy_id: int = Field(ge=1)
    as_of: datetime | None = None
    evaluation_key: str | None = Field(default=None, min_length=1, max_length=200)


def _dec(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _fail(exc: RiskError) -> None:
    raise ApiError(exc.code, exc.message, status_code=exc.status_code, details=exc.details) from exc


def _split_inst_ids(raw: str | None) -> tuple[str, ...] | None:
    if raw is None:
        return None
    items = tuple(part.strip() for part in raw.split(",") if part.strip())
    return items or None


@router.get("/policy")
async def read_policy(
    session: SessionDep,
    strategy_id: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    """读取最新阈值；不存在时用配置默认值建 v1。"""

    scope = "global" if strategy_id is None else "strategy"
    try:
        policy = await service.get_or_create_policy(session, scope=scope, strategy_id=strategy_id)
    except RiskError as exc:
        _fail(exc)
    return service.policy_view(policy)


@router.put("/policy")
async def write_policy(
    payload: UpdatePolicyRequest,
    session: SessionDep,
) -> dict[str, Any]:
    """更新阈值并返回新版本；版本过期 409，非法阈值 422。"""

    scope = "global" if payload.strategy_id is None else "strategy"
    thresholds = {
        field: _as_decimal(value)
        for field in service.THRESHOLD_FIELDS
        if (value := getattr(payload.thresholds, field)) is not None
    }
    try:
        policy = await service.update_policy(
            session,
            thresholds=thresholds,
            expected_version=payload.expected_version,
            updated_by=payload.updated_by,
            note=payload.note,
            scope=scope,
            strategy_id=payload.strategy_id,
        )
    except RiskError as exc:
        _fail(exc)
    return service.policy_view(policy)


@router.get("/status")
async def read_status(
    session: SessionDep,
    strategy_id: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    """当前是否允许增加敞口、命中哪条限额。只读，不落事件。"""

    try:
        return await service.status(session, strategy_id=strategy_id)
    except RiskError as exc:
        _fail(exc)


@router.get("/events")
async def read_events(
    session: SessionDep,
    kind: Literal["limit_breach", "drawdown", "funding", "liquidity"] | None = None,
    severity: Literal["tier1", "tier2", "tier3"] | None = None,
    strategy_id: int | None = Query(default=None, ge=1),
    since: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
) -> dict[str, Any]:
    """分页列出风险事件（按 id 倒序）。"""

    parsed_cursor: int | None = None
    if cursor is not None:
        try:
            parsed_cursor = int(cursor)
        except ValueError as exc:
            raise ApiError(
                "invalid_request",
                "cursor 必须是风险事件 id",
                status_code=400,
                details={"cursor": cursor},
            ) from exc
    return await service.list_events(
        session,
        kind=kind,
        severity=severity,
        strategy_id=strategy_id,
        since=since,
        limit=limit,
        cursor=parsed_cursor,
    )


@router.get("/funding")
async def read_funding(
    session: SessionDep,
    strategy_id: int | None = Query(default=None, ge=1),
    inst_ids: str | None = Query(default=None, description="逗号分隔的 instId 列表"),
) -> dict[str, Any]:
    """当前资金费率与盘口深度观测；任一标的取不到数据即 503。"""

    settings = get_settings()
    client = OkxClient(
        settings.okx_rest_base_url,
        settings.okx_http_timeout_seconds,
        candles_rate_limit=settings.okx_candles_rate_limit,
        history_rate_limit=settings.okx_history_rate_limit,
        window_seconds=settings.okx_rate_limit_window_seconds,
        max_retries=settings.okx_max_retries,
        backoff_seconds=settings.okx_retry_backoff_seconds,
    )
    source = OkxRiskMarketSource(client, book_depth=settings.risk_funding_book_depth)
    try:
        return await service.observe_funding(
            session,
            source=source,
            strategy_id=strategy_id,
            inst_ids=_split_inst_ids(inst_ids),
            persist=False,
        )
    except RiskError as exc:
        _fail(exc)
    except UpstreamUnavailable as exc:
        raise ApiError(
            "dependency_unavailable",
            "上游行情不可用",
            status_code=503,
            details={"reason": str(exc)},
        ) from exc
    except UpstreamError as exc:
        raise ApiError(
            "dependency_unavailable",
            "上游行情返回异常",
            status_code=503,
            details={"reason": str(exc)},
        ) from exc
    finally:
        await client.aclose()


@router.post("/evaluate", status_code=status.HTTP_202_ACCEPTED)
async def trigger_evaluate(
    payload: EvaluateRequest,
    response: Response,
    session: SessionDep,
) -> dict[str, Any]:
    """排队一次策略风控评估；同参数重复提交复用同一 job。"""

    job_payload: dict[str, Any] = {
        "strategy_id": payload.strategy_id,
        "as_of": _iso(payload.as_of),
        "evaluation_key": payload.evaluation_key,
    }
    job, created = await job_runs.create_run(
        session, job_name=tasks.RISK_EVALUATE, payload=job_payload
    )
    body = {
        "run_id": job.id,
        "job_id": job.id,
        "status": job.status,
        "run_key": job.job_key,
        "created": created,
        "dispatched": created,
    }
    if not created:
        response.status_code = status.HTTP_200_OK
        return body

    await dispatch(
        tasks.RISK_EVALUATE,
        run_id=job.id,
        strategy_id=payload.strategy_id,
        as_of=job_payload["as_of"],
        evaluation_key=payload.evaluation_key,
    )
    response.headers["Location"] = f"/api/v1/ops/job-runs/{job.id}"
    return body


def _as_decimal(value: Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


__all__ = ["router"]

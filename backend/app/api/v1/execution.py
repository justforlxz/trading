"""`/api/v1/execution`：订单、持仓、账户、对账、恢复与止损（只做协议编排）。

两类下单端点刻意分开：

* `POST /execution/orders` 是**真实**下单，`REAL_TRADING_ENABLED` 未显式打开时
  一律 403 `real_trading_disabled`（出口门禁依赖这一点，因此门禁检查在
  请求体校验之前）。
* `POST /execution/paper/orders` 是模拟下单，任何模式下都可用，且不会触达交易所。

两者最终都走 `app.execution.service.submit_order`，共用同一套订单生命周期。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.okx.rate_limit import UpstreamError, UpstreamUnavailable
from app.api.errors import ApiError
from app.api.v1.deps import session_dep
from app.config import get_settings
from app.execution import gate as execution_gate
from app.execution import reconcile, recovery, service, stops
from app.execution.core import orders as order_core
from app.execution.errors import ExecutionError

router = APIRouter(prefix="/execution", tags=["execution"])
SessionDep = Annotated[AsyncSession, Depends(session_dep)]

MAX_LIMIT = 200


class SubmitOrderRequest(BaseModel):
    strategy_id: int = Field(ge=1)
    inst_id: str = Field(min_length=1, max_length=64)
    side: Literal["buy", "sell"]
    position_side: Literal["long", "short"]
    quantity: Decimal = Field(gt=0)
    order_type: Literal["market", "limit"] = "market"
    price: Decimal | None = Field(default=None, gt=0)
    reduce_only: bool = False
    intent: Literal["entry", "exit", "stop"] = "entry"
    client_order_id: str | None = Field(default=None, min_length=1, max_length=32)


class ResolveDiffRequest(BaseModel):
    resolved_by: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


class StopsRequest(BaseModel):
    threshold_ratio: Decimal | None = Field(default=None, gt=0, le=1)
    persist: bool = True


def _fail(exc: Exception) -> None:
    if isinstance(exc, ExecutionError):
        raise ApiError(
            exc.code, exc.message, status_code=exc.status_code, details=exc.details
        ) from exc
    if isinstance(exc, UpstreamUnavailable | UpstreamError):
        raise ApiError(
            "dependency_unavailable",
            "交易所接口不可用",
            status_code=503,
            details={"reason": str(exc)},
        ) from exc
    raise exc


async def _submit(
    session: AsyncSession,
    payload: SubmitOrderRequest,
    response: Response,
    *,
    mode: str,
) -> dict[str, Any]:
    try:
        body, created = await service.submit_order(
            session,
            strategy_id=payload.strategy_id,
            inst_id=payload.inst_id,
            side=payload.side,
            position_side=payload.position_side,
            quantity=payload.quantity,
            order_type=payload.order_type,
            price=payload.price,
            reduce_only=payload.reduce_only,
            intent=payload.intent,
            client_order_id=payload.client_order_id,
            mode=mode,
        )
    except (ExecutionError, UpstreamError, UpstreamUnavailable, order_core.OrderStateError) as exc:
        if isinstance(exc, order_core.OrderStateError):
            raise ApiError("execution_invalid_transition", str(exc), status_code=409) from exc
        _fail(exc)
    if not created:
        response.status_code = status.HTTP_200_OK
    else:
        response.headers["Location"] = f"/api/v1/execution/orders/{body['id']}"
    return body


@router.get("/mode")
async def read_mode() -> dict[str, Any]:
    """当前执行模式与真实交易的关闭原因。"""

    return service.mode_view()


@router.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_real_order(
    response: Response,
    session: SessionDep,
    payload: SubmitOrderRequest | None = None,
) -> dict[str, Any]:
    """真实下单；`REAL_TRADING_ENABLED` 缺省 false 时即使无请求体也回 403。"""

    if not get_settings().real_trading_enabled:
        raise ApiError(
            execution_gate.CODE_REAL_DISABLED,
            "真实交易未开启 (REAL_TRADING_ENABLED 缺省为 false)",
            status_code=403,
        )
    if payload is None:
        raise ApiError("VALIDATION_ERROR", "请求体缺失", status_code=422)
    return await _submit(session, payload, response, mode=service.MODE_REAL)


@router.post("/paper/orders", status_code=status.HTTP_201_CREATED)
async def create_paper_order(
    payload: SubmitOrderRequest,
    response: Response,
    session: SessionDep,
) -> dict[str, Any]:
    """模拟下单；不触达交易所，成交由 paper 撮合器生成。"""

    return await _submit(session, payload, response, mode=service.MODE_PAPER)


@router.get("/orders")
async def list_orders(
    session: SessionDep,
    strategy_id: int | None = Query(default=None, ge=1),
    state: Literal["pending", "submitted", "partial", "filled", "canceled", "rejected"]
    | None = None,
    mode: Literal["paper", "real"] | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
) -> dict[str, Any]:
    parsed_cursor = _cursor(cursor)
    return await service.list_orders(
        session,
        strategy_id=strategy_id,
        state=state,
        mode=mode,
        limit=limit,
        cursor=parsed_cursor,
    )


@router.get("/orders/{order_id}")
async def read_order(order_id: int, session: SessionDep) -> dict[str, Any]:
    try:
        return await service.order_view(session, order_id)
    except ExecutionError as exc:
        _fail(exc)


@router.post("/orders/{order_id}/sync")
async def sync_order(order_id: int, session: SessionDep) -> dict[str, Any]:
    try:
        return await service.poll_order(session, order_id)
    except (ExecutionError, UpstreamError, UpstreamUnavailable) as exc:
        _fail(exc)


@router.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: int, session: SessionDep) -> dict[str, Any]:
    try:
        return await service.cancel_order(session, order_id)
    except (ExecutionError, UpstreamError, UpstreamUnavailable) as exc:
        _fail(exc)


@router.get("/positions")
async def read_positions(
    session: SessionDep,
    strategy_id: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    return await service.positions_view(session, strategy_id=strategy_id)


@router.get("/account")
async def read_account(session: SessionDep) -> dict[str, Any]:
    return await service.account_view(session)


@router.post("/reconcile")
async def run_reconcile(session: SessionDep) -> dict[str, Any]:
    try:
        async with service.source_for(session, service.resolve_mode(), None) as active:
            return await reconcile.run(session, source=active)
    except (UpstreamError, UpstreamUnavailable) as exc:
        _fail(exc)


@router.get("/reconcile/diffs")
async def read_diffs(
    session: SessionDep,
    status_filter: Literal["open", "resolved"] | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
) -> dict[str, Any]:
    return await reconcile.list_diffs(
        session, status=status_filter, limit=limit, cursor=_cursor(cursor)
    )


@router.post("/reconcile/diffs/{diff_id}/resolve")
async def resolve_diff(
    diff_id: int, payload: ResolveDiffRequest, session: SessionDep
) -> dict[str, Any]:
    try:
        return await reconcile.resolve_diff(
            session, diff_id, resolved_by=payload.resolved_by, note=payload.note
        )
    except ExecutionError as exc:
        _fail(exc)


@router.post("/recovery")
async def run_recovery(session: SessionDep) -> dict[str, Any]:
    try:
        return await recovery.run(session)
    except (UpstreamError, UpstreamUnavailable) as exc:
        _fail(exc)


@router.post("/stops/evaluate")
async def evaluate_stops(payload: StopsRequest, session: SessionDep) -> dict[str, Any]:
    try:
        return await stops.evaluate(
            session, threshold_ratio=payload.threshold_ratio, persist=payload.persist
        )
    except (UpstreamError, UpstreamUnavailable) as exc:
        _fail(exc)
    except ExecutionError as exc:
        _fail(exc)


def _cursor(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ApiError(
            "invalid_request",
            "cursor 必须是整数 id",
            status_code=400,
            details={"cursor": raw},
        ) from exc


__all__ = ["router"]

"""`/api/v1/ai/*`: 只读解释、只读问答与策略草案建议。

这一层是**组合根**: 它把当前请求的会话交给 `app.adapters.domain.registry` 装配出只读
端口, 再转给 `app.ai.service`。`app.ai` 因此不需要 import 任何业务域模块或适配器。
这里不直接调用外部 HTTP, 也不直接读写任何交易域数据。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.domain import registry
from app.ai import service
from app.ai.errors import AI_INVALID_REQUEST, AiError
from app.api.errors import ApiError, request_id_of
from app.api.v1.deps import session_dep
from app.market.core.bars import normalize_bar

router = APIRouter(prefix="/ai", tags=["ai"])

SessionDep = Annotated[AsyncSession, Depends(session_dep)]


class MarketExplainRequest(BaseModel):
    as_of: datetime | None = None
    bar: str | None = None
    scope: str | None = None


class RelationsExplainRequest(BaseModel):
    target_id: int
    window_bars: int | None = None
    method: str | None = None
    price_basis: str | None = None


class StrategyExplainRequest(BaseModel):
    strategy_id: int


class BacktestExplainRequest(BaseModel):
    run_id: int


class QueryRequest(BaseModel):
    question: str
    limit: int | None = None


class SuggestRequest(BaseModel):
    opportunity_id: int | None = None
    target_id: int | None = None
    params: dict[str, Any] | None = None


async def _call(coro: Any) -> dict[str, Any]:
    """把助手域错误翻译成统一信封, 避免冒泡成 500。"""

    try:
        return await coro
    except AiError as exc:
        raise ApiError(
            exc.code, exc.message, status_code=exc.status_code, details=exc.details
        ) from exc


def _normalized_bar(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return normalize_bar(value)
    except ValueError as exc:
        raise ApiError(AI_INVALID_REQUEST, f"不支持的 bar: {value}", status_code=422) from exc


@router.post("/explain/market")
async def explain_market(
    body: MarketExplainRequest, request: Request, session: SessionDep
) -> dict[str, Any]:
    bar = _normalized_bar(body.bar)
    return await _call(
        service.explain_market(
            session,
            registry.build_ai_reads(session),
            request_id=request_id_of(request),
            as_of=body.as_of,
            bar=bar,
            scope=body.scope,
        )
    )


@router.post("/explain/relations")
async def explain_relations(
    body: RelationsExplainRequest, request: Request, session: SessionDep
) -> dict[str, Any]:
    return await _call(
        service.explain_relations(
            session,
            registry.build_ai_reads(session),
            request_id=request_id_of(request),
            target_id=body.target_id,
            window_bars=body.window_bars,
            method=body.method,
            price_basis=body.price_basis,
        )
    )


@router.post("/explain/strategy")
async def explain_strategy(
    body: StrategyExplainRequest, request: Request, session: SessionDep
) -> dict[str, Any]:
    return await _call(
        service.explain_strategy(
            session,
            registry.build_ai_reads(session),
            request_id=request_id_of(request),
            strategy_id=body.strategy_id,
        )
    )


@router.post("/explain/backtest")
async def explain_backtest(
    body: BacktestExplainRequest, request: Request, session: SessionDep
) -> dict[str, Any]:
    return await _call(
        service.explain_backtest(
            session,
            registry.build_ai_reads(session),
            request_id=request_id_of(request),
            run_id=body.run_id,
        )
    )


@router.post("/query")
async def query(body: QueryRequest, request: Request, session: SessionDep) -> dict[str, Any]:
    return await _call(
        service.query(
            session,
            registry.build_ai_reads(session),
            request_id=request_id_of(request),
            question=body.question,
            limit=body.limit,
        )
    )


@router.post("/suggest/strategy")
async def suggest_strategy(
    body: SuggestRequest, request: Request, session: SessionDep
) -> dict[str, Any]:
    return await _call(
        service.suggest_strategy(
            session,
            registry.build_ai_reads(session),
            request_id=request_id_of(request),
            opportunity_id=body.opportunity_id,
            target_id=body.target_id,
            params=body.params,
        )
    )


__all__ = ["router"]

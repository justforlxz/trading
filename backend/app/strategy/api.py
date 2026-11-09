"""策略 API：只做请求解析与响应编排，计算与落库分别落在 core 和 service。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.v1.deps import session_dep
from app.strategy import service
from app.strategy.core.constraints import ConstraintViolation
from app.strategy.schemas import (
    ApproveRequest,
    CreateStrategyRequest,
    PatchStrategyRequest,
    RejectRequest,
    StrategyKind,
    StrategyStatus,
)
from app.strategy.service import (
    approval_payload,
    strategy_detail,
    strategy_payload,
    transition_payload,
)

router = APIRouter(prefix="/strategies", tags=["strategy"])
SessionDep = Annotated[AsyncSession, Depends(session_dep)]

MAX_LIMIT = 200
DEFAULT_LIMIT = 50
ActorHeader = Annotated[str | None, Header(alias="X-Actor")]


def _fail(exc: ConstraintViolation) -> None:
    raise ApiError(exc.code, exc.message, status_code=exc.status_code, details=exc.details) from exc


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("")
async def list_strategies(
    session: SessionDep,
    status: StrategyStatus | None = None,
    kind: StrategyKind | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
) -> dict[str, Any]:
    cursor_id: int | None = None
    if cursor:
        try:
            cursor_id = int(cursor)
        except ValueError as exc:
            raise ApiError("INVALID_CURSOR", "cursor must be a strategy id") from exc
    rows, next_cursor = await service.list_strategies(
        session,
        status=status.value if status else None,
        kind=kind.value if kind else None,
        limit=limit,
        cursor=cursor_id,
    )
    reviewers = await service.latest_reviewers(session, [row.id for row in rows])
    legs_by_strategy = await service.load_legs_many(session, [row.id for row in rows])
    return {
        "items": [
            strategy_payload(
                row,
                legs=legs_by_strategy.get(row.id, []),
                reviewer=reviewers.get(row.id),
            )
            for row in rows
        ],
        "next_cursor": str(next_cursor) if next_cursor is not None else None,
    }


@router.post("", status_code=201)
async def create_strategy(
    payload: CreateStrategyRequest,
    request: Request,
    response: Response,
    session: SessionDep,
) -> dict[str, Any]:
    try:
        row, created = await service.create_strategy(
            session, payload, request_id=_request_id(request)
        )
    except ConstraintViolation as exc:
        _fail(exc)
    if not created:
        response.status_code = 200
    legs = await service.load_legs(session, row.id)
    return strategy_payload(row, legs=legs)


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: int, session: SessionDep) -> dict[str, Any]:
    try:
        return await strategy_detail(session, strategy_id)
    except ConstraintViolation as exc:
        _fail(exc)


@router.patch("/{strategy_id}")
async def patch_strategy(
    strategy_id: int, payload: PatchStrategyRequest, session: SessionDep
) -> dict[str, Any]:
    try:
        await service.patch_strategy(session, strategy_id, payload)
        return await strategy_detail(session, strategy_id)
    except ConstraintViolation as exc:
        _fail(exc)


@router.post("/{strategy_id}/submit")
async def submit_strategy(
    strategy_id: int,
    request: Request,
    session: SessionDep,
    x_actor: ActorHeader = None,
) -> dict[str, Any]:
    try:
        await service.transition(
            session,
            strategy_id,
            "submit",
            actor=x_actor or "user",
            request_id=_request_id(request),
        )
        return await strategy_detail(session, strategy_id)
    except ConstraintViolation as exc:
        _fail(exc)


@router.post("/{strategy_id}/approve")
async def approve_strategy(
    strategy_id: int,
    payload: ApproveRequest,
    request: Request,
    session: SessionDep,
) -> dict[str, Any]:
    try:
        await service.transition(
            session,
            strategy_id,
            "approve",
            actor=payload.reviewer,
            note=payload.note,
            reason=payload.note,
            request_id=_request_id(request),
        )
        return await strategy_detail(session, strategy_id)
    except ConstraintViolation as exc:
        _fail(exc)


@router.post("/{strategy_id}/reject")
async def reject_strategy(
    strategy_id: int,
    payload: RejectRequest,
    request: Request,
    session: SessionDep,
) -> dict[str, Any]:
    try:
        await service.transition(
            session,
            strategy_id,
            "reject",
            actor=payload.reviewer,
            note=payload.note,
            reason=payload.note,
            request_id=_request_id(request),
        )
        return await strategy_detail(session, strategy_id)
    except ConstraintViolation as exc:
        _fail(exc)


@router.post("/{strategy_id}/archive")
async def archive_strategy(
    strategy_id: int,
    request: Request,
    session: SessionDep,
    x_actor: ActorHeader = None,
) -> dict[str, Any]:
    try:
        await service.transition(
            session,
            strategy_id,
            "archive",
            actor=x_actor or "user",
            request_id=_request_id(request),
        )
        return await strategy_detail(session, strategy_id)
    except ConstraintViolation as exc:
        _fail(exc)


@router.get("/{strategy_id}/approvals")
async def list_approvals(strategy_id: int, session: SessionDep) -> dict[str, Any]:
    try:
        await service.get_strategy(session, strategy_id)
    except ConstraintViolation as exc:
        _fail(exc)
    rows = await service.load_approvals(session, strategy_id)
    return {"items": [approval_payload(row) for row in rows]}


@router.get("/{strategy_id}/transitions")
async def list_transitions(strategy_id: int, session: SessionDep) -> dict[str, Any]:
    try:
        await service.get_strategy(session, strategy_id)
    except ConstraintViolation as exc:
        _fail(exc)
    rows = await service.load_transitions(session, strategy_id)
    return {"items": [transition_payload(row) for row in rows]}


__all__ = ["router"]

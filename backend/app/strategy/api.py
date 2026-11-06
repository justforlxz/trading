"""策略 API：只做请求解析与响应编排，计算与落库分别落在 core 和 service。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.v1.deps import session_dep
from app.strategy import service
from app.strategy.core.constraints import ConstraintViolation
from app.strategy.models import Strategy, StrategyApproval, StrategyLeg, StrategyTransition
from app.strategy.schemas import (
    ApproveRequest,
    CreateStrategyRequest,
    PatchStrategyRequest,
    RejectRequest,
    StrategyKind,
    StrategyStatus,
)

router = APIRouter(prefix="/strategies", tags=["strategy"])
SessionDep = Annotated[AsyncSession, Depends(session_dep)]

MAX_LIMIT = 200
DEFAULT_LIMIT = 50
ActorHeader = Annotated[str | None, Header(alias="X-Actor")]


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


def _symbol(inst_id: str, uly: str | None) -> str:
    return (uly or inst_id.split("-")[0]).upper()


def _fail(exc: ConstraintViolation) -> None:
    raise ApiError(exc.code, exc.message, status_code=exc.status_code, details=exc.details) from exc


def _leg_payload(row: StrategyLeg, inst_id: str, uly: str | None) -> dict[str, Any]:
    return {
        "id": row.id,
        "instrument_id": row.instrument_id,
        "inst_id": inst_id,
        "symbol": _symbol(inst_id, uly),
        "side": row.side,
        "weight": _dec(row.target_weight),
        "rationale": row.rationale,
        "rank": row.rank,
    }


def _approval_payload(row: StrategyApproval) -> dict[str, Any]:
    return {
        "id": row.id,
        "decision": row.decision,
        "content_hash": row.content_hash,
        "reviewer": row.reviewer,
        "note": row.note,
        "decided_at": _iso(row.decided_at),
    }


def _transition_payload(row: StrategyTransition) -> dict[str, Any]:
    return {
        "id": row.id,
        "from_status": row.from_status,
        "to_status": row.to_status,
        "at": _iso(row.at),
        "actor": row.actor,
        "reason": row.reason,
        "request_id": row.request_id,
    }


def _strategy_payload(
    row: Strategy,
    *,
    legs: list[tuple[StrategyLeg, str, str | None]] | None = None,
    approvals: list[StrategyApproval] | None = None,
    transitions: list[StrategyTransition] | None = None,
    reviewer: str | None = None,
) -> dict[str, Any]:
    params = dict(row.params or {})
    payload: dict[str, Any] = {
        "id": row.id,
        "strategy_key": row.strategy_key,
        "name": row.name,
        "kind": row.kind,
        "status": row.status,
        "target_id": row.target_id,
        "templates": list(row.templates or []),
        "params": params,
        "source": params.get("source"),
        "exclusions": params.get("exclusions", []),
        "content_hash": row.content_hash,
        "version": row.version,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "approved_at": _iso(row.approved_at),
        "reviewer": reviewer,
        "legs": [_leg_payload(leg, inst_id, uly) for leg, inst_id, uly in (legs or [])],
    }
    if approvals is not None:
        payload["approvals"] = [_approval_payload(item) for item in approvals]
    if transitions is not None:
        payload["transitions"] = [_transition_payload(item) for item in transitions]
    return payload


async def _detail(session: AsyncSession, strategy_id: int) -> dict[str, Any]:
    row = await service.get_strategy(session, strategy_id)
    legs = await service.load_legs(session, strategy_id)
    approvals = await service.load_approvals(session, strategy_id)
    transitions = await service.load_transitions(session, strategy_id)
    reviewer = approvals[0].reviewer if approvals else None
    return _strategy_payload(
        row,
        legs=legs,
        approvals=approvals,
        transitions=transitions,
        reviewer=reviewer,
    )


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
            _strategy_payload(
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
    return _strategy_payload(row, legs=legs)


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: int, session: SessionDep) -> dict[str, Any]:
    try:
        return await _detail(session, strategy_id)
    except ConstraintViolation as exc:
        _fail(exc)


@router.patch("/{strategy_id}")
async def patch_strategy(
    strategy_id: int, payload: PatchStrategyRequest, session: SessionDep
) -> dict[str, Any]:
    try:
        await service.patch_strategy(session, strategy_id, payload)
        return await _detail(session, strategy_id)
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
        return await _detail(session, strategy_id)
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
        return await _detail(session, strategy_id)
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
        return await _detail(session, strategy_id)
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
        return await _detail(session, strategy_id)
    except ConstraintViolation as exc:
        _fail(exc)


@router.get("/{strategy_id}/approvals")
async def list_approvals(strategy_id: int, session: SessionDep) -> dict[str, Any]:
    try:
        await service.get_strategy(session, strategy_id)
    except ConstraintViolation as exc:
        _fail(exc)
    rows = await service.load_approvals(session, strategy_id)
    return {"items": [_approval_payload(row) for row in rows]}


@router.get("/{strategy_id}/transitions")
async def list_transitions(strategy_id: int, session: SessionDep) -> dict[str, Any]:
    try:
        await service.get_strategy(session, strategy_id)
    except ConstraintViolation as exc:
        _fail(exc)
    rows = await service.load_transitions(session, strategy_id)
    return {"items": [_transition_payload(row) for row in rows]}


__all__ = ["router"]

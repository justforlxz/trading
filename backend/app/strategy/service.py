"""策略服务：编排生成、落库与审批状态迁移（不含任何决策计算）。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.market.models import Instrument
from app.strategy.core.builder import BuiltLeg, build_legs
from app.strategy.core.constraints import ConstraintViolation, check_legs
from app.strategy.core.hash import content_hash, strategy_key
from app.strategy.models import (
    Strategy,
    StrategyApproval,
    StrategyLeg,
    StrategyTransition,
)
from app.strategy.schemas import CreateStrategyRequest, PatchStrategyRequest
from app.strategy.sources import SourceResolution, resolve_opportunity, resolve_target
from app.strategy.state_machine import IllegalTransition, is_editable, next_status

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
RESERVED_PARAMS = frozenset({"source", "exclusions", "opportunity_id"})


def _check_limits(legs: Sequence[Any], limits: dict[str, Any]) -> None:
    check_legs(
        legs,
        min_legs=limits["min_legs"],
        max_legs=limits["max_legs"],
        max_position_weight=limits["max_position_weight"],
        max_gross_exposure=limits["max_gross_exposure"],
        max_net_exposure=limits["max_net_exposure"],
    )


async def _ensure_instruments(session: AsyncSession, legs: Sequence[Any]) -> None:
    """先确认 leg 引用的标的都存在，避免外键冲突变成 500。"""

    wanted = {leg.instrument_id for leg in legs}
    existing = set(
        (await session.execute(select(Instrument.id).where(Instrument.id.in_(wanted)))).scalars()
    )
    missing = sorted(wanted - existing)
    if missing:
        raise ConstraintViolation(
            "strategy_instrument_not_found",
            "leg instruments do not exist",
            details={"instrument_ids": missing},
        )


def _limits(params: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """阈值可由请求参数覆盖；非法值直接拒绝，不做钳制。"""

    try:
        limits: dict[str, Any] = {
            "max_position_weight": float(
                params.get("max_position_weight", settings.strategy_max_position_weight)
            ),
            "max_gross_exposure": float(
                params.get("max_gross_exposure", settings.strategy_max_gross_exposure)
            ),
            "max_net_exposure": float(
                params.get("max_net_exposure", settings.strategy_max_net_exposure)
            ),
            "min_legs": int(params.get("min_legs", settings.strategy_min_legs)),
            "max_legs": int(params.get("max_legs", settings.strategy_max_legs)),
        }
    except (TypeError, ValueError) as exc:
        raise ConstraintViolation(
            "strategy_invalid_param", f"invalid strategy limit: {exc}"
        ) from exc

    if not 0 < limits["max_position_weight"] <= 1:
        raise ConstraintViolation("strategy_invalid_param", "max_position_weight must be in (0, 1]")
    if limits["max_gross_exposure"] <= 0:
        raise ConstraintViolation("strategy_invalid_param", "max_gross_exposure must be > 0")
    if not 0 <= limits["max_net_exposure"] <= limits["max_gross_exposure"]:
        raise ConstraintViolation(
            "strategy_invalid_param", "max_net_exposure must be in [0, max_gross_exposure]"
        )
    if limits["min_legs"] < 1:
        raise ConstraintViolation("strategy_invalid_param", "min_legs must be >= 1")
    if limits["max_legs"] < limits["min_legs"]:
        raise ConstraintViolation("strategy_invalid_param", "max_legs must be >= min_legs")
    return limits


async def _resolve(
    session: AsyncSession,
    payload: CreateStrategyRequest,
    params: dict[str, Any],
    settings: Settings,
) -> SourceResolution:
    opportunity_id = params.get("opportunity_id")
    if opportunity_id is not None:
        return await resolve_opportunity(
            session, opportunity_id=int(opportunity_id), kind=payload.kind.value, settings=settings
        )
    if payload.target_id is not None:
        return await resolve_target(
            session, target_id=payload.target_id, kind=payload.kind.value, settings=settings
        )
    raise ConstraintViolation(
        "strategy_source_required",
        "provide target_id or params.opportunity_id to generate a strategy",
    )


async def create_strategy(
    session: AsyncSession, payload: CreateStrategyRequest, *, request_id: str | None = None
) -> tuple[Strategy, bool]:
    """生成并落库；同一 `strategy_key` 已存在时返回既有记录（created=False）。"""

    settings = get_settings()
    params = dict(payload.params)
    limits = _limits(params, settings)
    resolution = await _resolve(session, payload, params, settings)

    legs = build_legs(
        resolution.candidates,
        templates=list(payload.templates),
        max_position_weight=limits["max_position_weight"],
        max_gross_exposure=limits["max_gross_exposure"],
        max_net_exposure=limits["max_net_exposure"],
        min_legs=limits["min_legs"],
        max_legs=limits["max_legs"],
        window_bars=resolution.window_bars,
    )
    stored_params = {
        **params,
        "source": resolution.source,
        "exclusions": resolution.exclusions,
        "limits": limits,
    }
    key = strategy_key(
        kind=payload.kind.value,
        target_id=payload.target_id,
        templates=list(payload.templates),
        params=stored_params,
        legs=legs,
    )
    digest = content_hash(
        kind=payload.kind.value,
        target_id=payload.target_id,
        templates=list(payload.templates),
        params=stored_params,
        legs=legs,
    )

    existing = (
        await session.execute(select(Strategy).where(Strategy.strategy_key == key))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    strategy = Strategy(
        strategy_key=key,
        name=payload.name,
        kind=payload.kind.value,
        status="draft",
        target_id=payload.target_id,
        templates=list(payload.templates),
        params=stored_params,
        content_hash=digest,
        version=1,
    )
    session.add(strategy)
    await session.flush()
    for leg in legs:
        session.add(
            StrategyLeg(
                strategy_id=strategy.id,
                instrument_id=leg.instrument_id,
                side=leg.side,
                target_weight=leg.target_weight,
                rationale=leg.rationale,
                rank=leg.rank,
            )
        )
    await session.commit()
    return strategy, True


async def get_strategy(session: AsyncSession, strategy_id: int) -> Strategy:
    strategy = await session.get(Strategy, strategy_id)
    if strategy is None:
        raise ConstraintViolation(
            "STRATEGY_NOT_FOUND",
            f"strategy {strategy_id} not found",
            status_code=404,
            details={"strategy_id": strategy_id},
        )
    return strategy


async def load_legs(session: AsyncSession, strategy_id: int) -> list[tuple[StrategyLeg, str, str]]:
    return (await load_legs_many(session, [strategy_id])).get(strategy_id, [])


async def load_legs_many(
    session: AsyncSession, strategy_ids: Sequence[int]
) -> dict[int, list[tuple[StrategyLeg, str, str]]]:
    if not strategy_ids:
        return {}
    rows = await session.execute(
        select(StrategyLeg, Instrument.inst_id, Instrument.uly)
        .join(Instrument, Instrument.id == StrategyLeg.instrument_id)
        .where(StrategyLeg.strategy_id.in_(strategy_ids))
        .order_by(StrategyLeg.strategy_id.asc(), StrategyLeg.rank.asc(), StrategyLeg.id.asc())
    )
    grouped: dict[int, list[tuple[StrategyLeg, str, str]]] = {}
    for leg, inst_id, uly in rows.all():
        grouped.setdefault(leg.strategy_id, []).append((leg, inst_id, uly))
    return grouped


async def load_approvals(session: AsyncSession, strategy_id: int) -> list[StrategyApproval]:
    rows = await session.execute(
        select(StrategyApproval)
        .where(StrategyApproval.strategy_id == strategy_id)
        .order_by(StrategyApproval.decided_at.desc(), StrategyApproval.id.desc())
    )
    return list(rows.scalars())


async def load_transitions(session: AsyncSession, strategy_id: int) -> list[StrategyTransition]:
    rows = await session.execute(
        select(StrategyTransition)
        .where(StrategyTransition.strategy_id == strategy_id)
        .order_by(StrategyTransition.at.asc(), StrategyTransition.id.asc())
    )
    return list(rows.scalars())


async def list_strategies(
    session: AsyncSession,
    *,
    status: str | None = None,
    kind: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: int | None = None,
) -> tuple[list[Strategy], int | None]:
    stmt = select(Strategy).order_by(Strategy.id.desc()).limit(limit + 1)
    if status:
        stmt = stmt.where(Strategy.status == status)
    if kind:
        stmt = stmt.where(Strategy.kind == kind)
    if cursor is not None:
        stmt = stmt.where(Strategy.id < cursor)
    rows = list((await session.execute(stmt)).scalars())
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return rows[:limit], next_cursor


async def latest_reviewers(session: AsyncSession, strategy_ids: list[int]) -> dict[int, str]:
    """列表页用的「最近一次审批人」；没有任何审批的策略不出现在返回值里。"""

    if not strategy_ids:
        return {}
    rows = (
        await session.execute(
            select(StrategyApproval)
            .where(StrategyApproval.strategy_id.in_(strategy_ids))
            .order_by(StrategyApproval.decided_at.desc(), StrategyApproval.id.desc())
        )
    ).scalars()
    reviewers: dict[int, str] = {}
    for row in rows:
        reviewers.setdefault(row.strategy_id, row.reviewer)
    return reviewers


def _legs_as_built(rows: list[StrategyLeg], inst_ids: dict[int, str]) -> list[BuiltLeg]:
    return [
        BuiltLeg(
            instrument_id=leg.instrument_id,
            inst_id=inst_ids.get(leg.instrument_id, ""),
            side=leg.side,
            target_weight=leg.target_weight,
            rationale=leg.rationale,
            rank=leg.rank,
        )
        for leg in rows
    ]


async def patch_strategy(
    session: AsyncSession, strategy_id: int, payload: PatchStrategyRequest
) -> Strategy:
    """仅 draft/rejected 可编辑；编辑后重算内容指纹并递增版本。"""

    strategy = await get_strategy(session, strategy_id)
    if not is_editable(strategy.status):
        raise ConstraintViolation(
            "strategy_readonly",
            f"strategy {strategy_id} is {strategy.status} and its content is read-only",
            status_code=409,
            details={"strategy_id": strategy_id, "status": strategy.status},
        )

    settings = get_settings()
    params = dict(strategy.params or {})
    limits = _limits(params, settings)
    existing_legs: list[Any] = [leg for leg, _inst, _uly in await load_legs(session, strategy_id)]

    if payload.name is not None:
        strategy.name = payload.name
    if payload.params is not None:
        reserved = sorted(RESERVED_PARAMS.intersection(payload.params))
        if reserved:
            raise ConstraintViolation(
                "strategy_reserved_param",
                "source provenance parameters are read-only",
                details={"strategy_id": strategy_id, "keys": reserved},
            )
        params = {**params, **payload.params}
        limits = _limits(params, settings)
        strategy.params = {**params, "limits": limits}

    # 限额可能在本次编辑中收紧：无论是否替换 legs，都要用当前限额重新校验。
    effective_legs: Sequence[Any] = payload.legs if payload.legs is not None else existing_legs
    if payload.legs is not None:
        await _ensure_instruments(session, payload.legs)
    _check_limits(effective_legs, limits)

    if payload.legs is not None:
        built = [
            BuiltLeg(
                instrument_id=leg.instrument_id,
                inst_id="",
                side=leg.side,
                target_weight=leg.target_weight,
                rationale=leg.rationale,
                rank=leg.rank,
            )
            for leg in payload.legs
        ]
    else:
        inst_ids = {
            instrument_id: inst_id
            for instrument_id, inst_id in (
                await session.execute(
                    select(Instrument.id, Instrument.inst_id).where(
                        Instrument.id.in_([leg.instrument_id for leg in existing_legs])
                    )
                )
            ).all()
        }
        built = _legs_as_built(existing_legs, inst_ids)

    new_content_hash = content_hash(
        kind=strategy.kind,
        target_id=strategy.target_id,
        templates=list(strategy.templates or []),
        params=dict(strategy.params or {}),
        legs=built,
    )
    new_strategy_key = strategy_key(
        kind=strategy.kind,
        target_id=strategy.target_id,
        templates=list(strategy.templates or []),
        params=dict(strategy.params or {}),
        legs=built,
    )
    conflict_id = (
        await session.execute(
            select(Strategy.id).where(
                Strategy.strategy_key == new_strategy_key, Strategy.id != strategy_id
            )
        )
    ).scalar_one_or_none()
    if conflict_id is not None:
        raise ConstraintViolation(
            "strategy_key_conflict",
            "edited content matches another strategy",
            status_code=409,
            details={"strategy_id": strategy_id, "existing_id": conflict_id},
        )

    if payload.legs is not None:
        await session.execute(delete(StrategyLeg).where(StrategyLeg.strategy_id == strategy_id))
        for leg in payload.legs:
            session.add(
                StrategyLeg(
                    strategy_id=strategy_id,
                    instrument_id=leg.instrument_id,
                    side=leg.side,
                    target_weight=leg.target_weight,
                    rationale=leg.rationale,
                    rank=leg.rank,
                )
            )
        await session.flush()

    strategy.content_hash = new_content_hash
    strategy.strategy_key = new_strategy_key
    strategy.version = (strategy.version or 1) + 1
    await session.commit()
    return strategy


async def transition(
    session: AsyncSession,
    strategy_id: int,
    action: str,
    *,
    actor: str,
    reason: str | None = None,
    note: str | None = None,
    request_id: str | None = None,
) -> Strategy:
    """执行一次状态迁移，并追加审计记录；非法迁移不改任何数据。"""

    # 行锁串行化终态变更：并发 approve/reject 只能有一个赢得迁移，
    # 否则会写出 approved 与 rejected 并存的矛盾审计记录。
    locked = await session.execute(
        select(Strategy.status).where(Strategy.id == strategy_id).with_for_update()
    )
    current_status = locked.scalar_one_or_none()
    if current_status is None:
        raise ConstraintViolation(
            "STRATEGY_NOT_FOUND",
            f"strategy {strategy_id} not found",
            status_code=404,
            details={"strategy_id": strategy_id},
        )
    try:
        target_status = next_status(current_status, action)
    except IllegalTransition as exc:
        raise ConstraintViolation(
            "strategy_illegal_transition",
            str(exc),
            status_code=409,
            details={
                "strategy_id": strategy_id,
                "status": current_status,
                "action": action,
            },
        ) from exc

    strategy = await get_strategy(session, strategy_id)

    now = datetime.now(UTC)
    if action in ("approve", "reject"):
        decision = "approved" if action == "approve" else "rejected"
        await session.execute(
            pg_insert(StrategyApproval)
            .values(
                strategy_id=strategy_id,
                decision=decision,
                content_hash=strategy.content_hash,
                reviewer=actor,
                note=note,
                decided_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_strategy_approval_key")
        )
    if action == "approve":
        strategy.approved_at = now

    session.add(
        StrategyTransition(
            strategy_id=strategy_id,
            from_status=current_status,
            to_status=target_status,
            at=now,
            actor=actor,
            reason=reason,
            request_id=request_id,
        )
    )
    strategy.status = target_status
    await session.commit()
    return strategy


# ---------------------------------------------------------------------------
# 只读响应视图
#
# Web API 与 MCP 共用同一份组装逻辑：同一策略在两个入口必须逐字段一致，
# 复制一份序列化代码迟早会漂移。这里只做格式化，不读也不写数据库。
# ---------------------------------------------------------------------------


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


def leg_payload(row: StrategyLeg, inst_id: str, uly: str | None) -> dict[str, Any]:
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


def approval_payload(row: StrategyApproval) -> dict[str, Any]:
    return {
        "id": row.id,
        "decision": row.decision,
        "content_hash": row.content_hash,
        "reviewer": row.reviewer,
        "note": row.note,
        "decided_at": _iso(row.decided_at),
    }


def transition_payload(row: StrategyTransition) -> dict[str, Any]:
    return {
        "id": row.id,
        "from_status": row.from_status,
        "to_status": row.to_status,
        "at": _iso(row.at),
        "actor": row.actor,
        "reason": row.reason,
        "request_id": row.request_id,
    }


def strategy_payload(
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
        "legs": [leg_payload(leg, inst_id, uly) for leg, inst_id, uly in (legs or [])],
    }
    if approvals is not None:
        payload["approvals"] = [approval_payload(item) for item in approvals]
    if transitions is not None:
        payload["transitions"] = [transition_payload(item) for item in transitions]
    return payload


async def strategy_detail(session: AsyncSession, strategy_id: int) -> dict[str, Any]:
    """单条策略的完整视图：Web `GET /strategies/{id}` 与 MCP `get_strategy` 共用。"""

    row = await get_strategy(session, strategy_id)
    # 写操作刚在同一会话里提交过时，`updated_at` 这类 server-side onupdate 列
    # 处于过期状态；在这里（await 上下文）刷新，避免读属性时触发同步 IO。
    await session.refresh(row)
    legs = await load_legs(session, strategy_id)
    approvals = await load_approvals(session, strategy_id)
    transitions = await load_transitions(session, strategy_id)
    reviewer = approvals[0].reviewer if approvals else None
    return strategy_payload(
        row,
        legs=legs,
        approvals=approvals,
        transitions=transitions,
        reviewer=reviewer,
    )


__all__ = [
    "approval_payload",
    "create_strategy",
    "get_strategy",
    "latest_reviewers",
    "leg_payload",
    "list_strategies",
    "load_approvals",
    "load_legs",
    "load_legs_many",
    "load_transitions",
    "patch_strategy",
    "strategy_detail",
    "strategy_payload",
    "transition",
    "transition_payload",
]

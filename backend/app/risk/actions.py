"""把分级处置计划变成订单意图，并覆盖同标的的待批准组合申请。

这是全仓**唯一**实现「风险处置覆盖待批准申请」的地方：

- 只覆盖同一策略实例、同一标的的 `pending` 申请，状态改为 `superseded`。
- 同一组合内其他标的的申请保持 `pending`。
- 处置动作不等待批准，直接返回执行层可用的 `OrderIntent`。
- 每次覆盖按被覆盖的申请各写一条风险事件，事件带 `overridden_approval_id`。
- 同一规则、同一标的、同一严重程度在同一时间窗内的重复判定只写一条事件（幂等）；
  严重程度升级不视为重复，仍会留下新事件。

覆盖发生在处置事务内；订单意图只是返回值，本层不调用执行服务、不产生真实订单。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import OrderIntent, ValidationError
from app.db import session_scope
from app.instrument import trading_rules
from app.portfolio import PENDING, SUPERSEDED, PortfolioAdjustmentRow
from app.risk.disposal import DisposalAction, DisposalPlan
from app.risk.model import RiskEventRow
from app.risk.service import RiskEngine

__all__ = [
    "DISPOSAL_IDEMPOTENCY_SECONDS",
    "DisposalOutcome",
    "DisposalRequest",
    "dispose",
]

ZERO = Decimal(0)
DISPOSAL_IDEMPOTENCY_SECONDS = 60
CLOSING_ACTIONS = frozenset(
    {DisposalAction.REDUCE, DisposalAction.STOP_LOSS, DisposalAction.LIQUIDATE}
)


@dataclass(frozen=True, slots=True)
class DisposalRequest:
    """执行一次处置需要的持仓与时间信息。

    `position_side` 用 `long` / `short`；数量是被处置标的当前持仓数量。
    `reduce_ratio` 只对 `reduce` 动作生效，`stop_loss` / `liquidate` 一律全平。
    """

    instance_id: str
    position_side: str
    position_qty: Decimal
    at: datetime
    reduce_ratio: Decimal = Decimal("0.5")
    order_type: str = "market"
    price: Decimal | None = None
    engine: RiskEngine | None = None
    actor: str = "risk-disposal"

    def __post_init__(self) -> None:
        if not self.instance_id.strip():
            raise ValidationError("处置必须给出策略实例")
        if self.position_side not in {"long", "short"}:
            raise ValidationError(f"持仓方向必须是 long / short, 实际 {self.position_side!r}")
        if not isinstance(self.position_qty, Decimal) or self.position_qty < ZERO:
            raise ValidationError(f"持仓数量必须是非负 Decimal, 实际 {self.position_qty!r}")
        if not isinstance(self.reduce_ratio, Decimal) or not ZERO < self.reduce_ratio <= 1:
            raise ValidationError(f"减仓比例必须在 0..1 之间, 实际 {self.reduce_ratio!r}")
        if self.at.tzinfo is None:
            raise ValidationError("处置时刻必须带时区")
        if not self.actor.strip():
            raise ValidationError("处置必须给出执行人")


@dataclass(frozen=True, slots=True)
class DisposalOutcome:
    """一次处置的结果：订单意图、被覆盖的申请与写入的事件。"""

    plan: DisposalPlan
    intents: tuple[OrderIntent, ...]
    event_ids: tuple[str, ...]
    overridden_approval_ids: tuple[str, ...]
    halted: bool


def dispose(plan: DisposalPlan, request: DisposalRequest) -> DisposalOutcome:
    """执行处置：构造订单意图、覆盖同标的的待批准申请、写风险事件。"""

    intents = _intents(plan, request)
    halt = DisposalAction.HALT_ALL in plan.actions
    was_halted = request.engine.halted if request.engine is not None else False
    if halt and request.engine is not None:
        request.engine.set_emergency_stop(True)

    try:
        with session_scope() as session:
            overridden = _supersede(session, plan, request)
            event_ids = _record_events(session, plan, request, overridden)
    except Exception:
        if halt and request.engine is not None:
            request.engine.set_emergency_stop(was_halted)
        raise

    return DisposalOutcome(
        plan=plan,
        intents=intents,
        event_ids=event_ids,
        overridden_approval_ids=overridden,
        halted=request.engine.halted if request.engine is not None else halt,
    )


def _intents(plan: DisposalPlan, request: DisposalRequest) -> tuple[OrderIntent, ...]:
    actions = set(plan.actions)
    if not actions & CLOSING_ACTIONS:
        return ()
    if request.position_qty <= ZERO:
        return ()

    rules = trading_rules(plan.inst_type)
    full_close = bool(actions & {DisposalAction.STOP_LOSS, DisposalAction.LIQUIDATE})
    qty = request.position_qty if full_close else request.position_qty * request.reduce_ratio
    if qty <= ZERO:
        raise ValidationError("处置数量必须为正")

    side = "sell" if request.position_side == "long" else "buy"
    return (
        OrderIntent(
            inst_id=plan.inst_id,
            side=side,
            qty=qty,
            order_type=request.order_type,
            price=request.price if request.order_type == "limit" else None,
            pos_side=request.position_side if rules.has_position_endpoint else "",
            reduce_only=rules.has_position_endpoint,
        ),
    )


def _supersede(session: Session, plan: DisposalPlan, request: DisposalRequest) -> tuple[str, ...]:
    rows = list(
        session.scalars(
            select(PortfolioAdjustmentRow)
            .where(
                PortfolioAdjustmentRow.instance_id == request.instance_id,
                PortfolioAdjustmentRow.status == PENDING,
            )
            .with_for_update()
        )
    )
    overridden: list[str] = []
    for row in rows:
        if not _targets_instrument(row.target_json, plan.inst_id):
            continue
        row.status = SUPERSEDED
        row.decided_by = request.actor
        row.decided_at = request.at
        row.decision_note = f"风险处置覆盖: {plan.rule}/{plan.severity.value}"
        overridden.append(row.adjustment_id)
    return tuple(overridden)


def _targets_instrument(target_json: str, inst_id: str) -> bool:
    try:
        payload = json.loads(target_json)
        legs = payload["legs"]
    except (TypeError, ValueError, KeyError) as exc:
        raise ValidationError(f"调整申请的目标组合无法解析: {target_json!r}") from exc
    return any(isinstance(leg, dict) and leg.get("inst_id") == inst_id for leg in legs)


def _record_events(
    session: Session,
    plan: DisposalPlan,
    request: DisposalRequest,
    overridden: tuple[str, ...],
) -> tuple[str, ...]:
    since = request.at - timedelta(seconds=DISPOSAL_IDEMPOTENCY_SECONDS)
    existing = list(
        session.scalars(
            select(RiskEventRow).where(
                RiskEventRow.instance_id == request.instance_id,
                RiskEventRow.rule == plan.rule,
                RiskEventRow.inst_id == plan.inst_id,
                RiskEventRow.severity == plan.severity.value,
                RiskEventRow.created_at >= since,
                RiskEventRow.created_at <= request.at,
            )
        )
    )
    existing_overridden = {row.overridden_approval_id for row in existing}
    event_ids: list[str] = []

    if overridden:
        for adjustment_id in overridden:
            if adjustment_id in existing_overridden:
                continue
            event_ids.append(_add_event(session, plan, request, adjustment_id))
    elif not existing:
        event_ids.append(_add_event(session, plan, request, None))
    return tuple(event_ids)


def _add_event(
    session: Session,
    plan: DisposalPlan,
    request: DisposalRequest,
    overridden_approval_id: str | None,
) -> str:
    event_id = "re_" + uuid4().hex[:24]
    session.add(
        RiskEventRow(
            event_id=event_id,
            instance_id=request.instance_id,
            inst_id=plan.inst_id,
            rule=plan.rule,
            detail=plan.detail,
            created_at=request.at,
            resolved_at=None,
            severity=plan.severity.value,
            action=plan.action_text,
            target_product_key=plan.product_key,
            overridden_approval_id=overridden_approval_id,
        )
    )
    return event_id

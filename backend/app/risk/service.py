"""风控入口：判定、拒绝落库与通过后才构造订单意图。

本层只做 IO 与事务边界。规则是纯函数，返回「哪几条被触发」；这里负责取标的行、
读取紧急停止开关、把每次拒绝写进 `risk_events`，并且只在全部检查通过之后才构造
`OrderIntent`。拒绝路径上没有订单对象可被误传，不存在「先造单再标记拒绝」。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select

from app.core import OrderIntent, ValidationError
from app.db import session_scope
from app.instrument import Instrument, list_instruments
from app.risk.model import RiskEventRow
from app.risk.rules import (
    RiskContext,
    RiskDecision,
    RiskLimits,
    RuleViolation,
    TradeRequest,
    evaluate,
)

__all__ = [
    "RiskAuthorization",
    "RiskEngine",
    "RiskEventRecord",
    "list_risk_events",
    "resolve_risk_event",
]

MAX_LIMIT = 500


@dataclass(frozen=True, slots=True)
class RiskEventRecord:
    """供 API 与测试读取的一条风险事件。"""

    event_id: str
    instance_id: str | None
    inst_id: str | None
    rule: str
    detail: str
    created_at: datetime
    resolved_at: datetime | None
    severity: str | None = None
    action: str | None = None
    target_product_key: str | None = None
    overridden_approval_id: str | None = None


@dataclass(frozen=True, slots=True)
class RiskAuthorization:
    """一次风控判定的完整结果；拒绝时 `intent` 必为 `None`。"""

    allowed: bool
    checked_rules: tuple[str, ...]
    violations: tuple[RuleViolation, ...]
    intent: OrderIntent | None


class RiskEngine:
    """持有紧急停止开关的风控入口。

    开关是进程内状态：本节点只交付开关本身，T6.5 与执行层负责把它接到外部控制。
    """

    def __init__(self, limits: RiskLimits | None = None) -> None:
        self._limits = limits or RiskLimits()
        self._halted = False

    @property
    def halted(self) -> bool:
        return self._halted

    def set_emergency_stop(self, halted: bool = True) -> None:
        """打开或关闭紧急停止；只影响之后的新开仓信号。"""

        self._halted = bool(halted)

    def evaluate(self, request: TradeRequest, context: RiskContext) -> RiskDecision:
        """只判定，不写库、不构造订单。"""

        instrument = _instrument(request.inst_id)
        return evaluate(request, instrument, context, self._limits, halted=self._halted)

    def authorize(self, request: TradeRequest, context: RiskContext) -> RiskAuthorization:
        """完整入口：通过时返回订单意图，拒绝时落事件并返回空意图。"""

        instrument = _instrument(request.inst_id)
        decision = evaluate(request, instrument, context, self._limits, halted=self._halted)
        if decision.violations:
            _record(request, decision.violations)
        intent = _build_intent(request) if decision.allowed else None
        return RiskAuthorization(
            allowed=decision.allowed,
            checked_rules=decision.checked_rules,
            violations=decision.violations,
            intent=intent,
        )


def _instrument(inst_id: str) -> Instrument:
    """按交易所标识取标的行；找不到就是参数错误，不凭空猜类别。"""

    for row in list_instruments():
        if row.symbol == inst_id:
            return row
    raise ValidationError(f"未找到标的 {inst_id}")


def _build_intent(request: TradeRequest) -> OrderIntent:
    """风控通过之后才调用：把请求变成执行层可接收的订单意图。"""

    return OrderIntent(
        inst_id=request.inst_id,
        side=request.side,
        qty=request.qty,
        order_type=request.order_type,
        price=request.price if request.order_type == "limit" else None,
        client_order_id=request.client_order_id,
        pos_side=request.pos_side,
        reduce_only=request.reduce_only,
    )


def _record(request: TradeRequest, violations: tuple[RuleViolation, ...]) -> None:
    """每次拒绝按触发的规则各写一条事件；写失败直接抛出，不把异常当放行。"""

    with session_scope() as session:
        for violation in violations:
            session.add(
                RiskEventRow(
                    event_id="re_" + uuid4().hex[:24],
                    instance_id=request.instance_id,
                    inst_id=request.inst_id,
                    rule=violation.rule,
                    detail=violation.detail,
                    created_at=request.ts,
                    resolved_at=None,
                )
            )


def list_risk_events(
    *,
    instance_id: str | None = None,
    inst_id: str | None = None,
    rule: str | None = None,
    limit: int = 200,
) -> tuple[tuple[RiskEventRecord, ...], int]:
    """按时间倒序列出风险事件；`total` 是过滤后的总条数。"""

    if not 1 <= limit <= MAX_LIMIT:
        raise ValidationError(f"limit 必须在 1..{MAX_LIMIT} 之间, 实际 {limit}")

    filters = []
    if instance_id is not None:
        filters.append(RiskEventRow.instance_id == instance_id)
    if inst_id is not None:
        filters.append(RiskEventRow.inst_id == inst_id)
    if rule is not None:
        filters.append(RiskEventRow.rule == rule)

    with session_scope() as session:
        statement = select(RiskEventRow)
        count_statement = select(func.count()).select_from(RiskEventRow)
        for condition in filters:
            statement = statement.where(condition)
            count_statement = count_statement.where(condition)
        rows = list(
            session.scalars(
                statement.order_by(
                    RiskEventRow.created_at.desc(), RiskEventRow.event_id.desc()
                ).limit(limit)
            )
        )
        total = int(session.scalar(count_statement) or 0)

    records = tuple(
        RiskEventRecord(
            event_id=row.event_id,
            instance_id=row.instance_id,
            inst_id=row.inst_id,
            rule=row.rule,
            detail=row.detail,
            created_at=row.created_at,
            resolved_at=row.resolved_at,
            severity=row.severity,
            action=row.action,
            target_product_key=row.target_product_key,
            overridden_approval_id=row.overridden_approval_id,
        )
        for row in rows
    )
    return records, total


def resolve_risk_event(event_id: str, *, at: datetime | None = None) -> RiskEventRecord | None:
    """把一条风险事件标记为已处置；不存在返回 `None`，重复标记保持第一次的时间。"""

    moment = _now() if at is None else at
    if moment.tzinfo is None:
        raise ValidationError("处置时刻必须带时区")
    with session_scope() as session:
        row = session.get(RiskEventRow, event_id)
        if row is None:
            return None
        if row.resolved_at is None:
            row.resolved_at = moment
            session.flush()
        return RiskEventRecord(
            event_id=row.event_id,
            instance_id=row.instance_id,
            inst_id=row.inst_id,
            rule=row.rule,
            detail=row.detail,
            created_at=row.created_at,
            resolved_at=row.resolved_at,
            severity=row.severity,
            action=row.action,
            target_product_key=row.target_product_key,
            overridden_approval_id=row.overridden_approval_id,
        )


def _now() -> datetime:
    return datetime.now(UTC)

"""审批端点：生命周期阶段的四个推进动作与推进记录列表。

端点只做入参校验与响应组装，转移是否合法、`validated` 有没有达标依据，全部由
`app.strategy.approval` 的状态机判定。四个动作对应四个目标阶段：

- 提交审核：`strategy_generation`（或 `opportunity_discovery` / `rejected`）→
  `pending_review`；
- 审核通过：`pending_review` → `backtested`，同时记下审核人与时刻；
- 驳回：`pending_review` / `backtested` → `rejected`；
- 申请实盘授权：`paper_trading` → `live_authorized`，只记录授权事实。

`validated` 与 `paper_trading` 没有端点：进入 `validated` 必须附上一份达标的验证报告
（由回测与量化验证的调用方构造），`paper_trading` 由模拟交易接手；契约里没有这两个
动作，因此不在这里凭空造路径。

实盘授权里的资金预算不在这里落库：已批准预算属于策略组合域（T7.1 的
`StrategyPortfolio.capital_budget`），本端点只检查它是个正数并记录授权这件事，不复制
第二份预算。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException

from app.api.schemas import (
    LiveAuthorizationRequest,
    StrategyApprovalDecisionRequest,
    StrategyApprovalListResponse,
    StrategyApprovalRequest,
    StrategyApprovalTransition,
)
from app.core import InvariantViolation, ValidationError
from app.strategy import (
    ApprovalTransition,
    advance,
    get_instance,
    latest_transition,
    list_transitions,
)

__all__ = ["approval_router"]

approval_router = APIRouter(tags=["approval"])


@approval_router.get("/approvals", response_model=StrategyApprovalListResponse)
def list_approvals() -> StrategyApprovalListResponse:
    """全部审批记录，最近写入的在前。记录只增不改，实例删除时随之级联删除。"""

    records, total = list_transitions()
    return StrategyApprovalListResponse(
        items=[_transition(record) for record in records], total=total
    )


@approval_router.post("/approvals", response_model=StrategyApprovalTransition, status_code=201)
def submit_for_review(payload: StrategyApprovalRequest) -> StrategyApprovalTransition:
    """提交人工审核：草稿阶段（或被驳回之后）进入待审核。

    机会发现阶段的实例不能直接提交：转移表要求先落到草稿（`strategy_generation`），
    再由人工提交，否则「审核」这一步会跳过策略生成。
    """

    return _advance(payload.instance_id, "pending_review", payload.actor, note=payload.note)


@approval_router.post("/approvals/{instance_id}/approve", response_model=StrategyApprovalTransition)
def approve_strategy(
    instance_id: str, payload: StrategyApprovalDecisionRequest
) -> StrategyApprovalTransition:
    """审核通过：进入历史回测阶段，并记下审核人与时刻。

    回测本身由回测域执行，本端点不跑回测；`validated` 也不是这一步——它必须由达标的
    回测报告驱动，见 `app.strategy.approval.advance`。
    """

    return _advance(
        instance_id,
        "backtested",
        payload.actor,
        evidence=payload.evidence,
        note=payload.note,
    )


@approval_router.post("/approvals/{instance_id}/reject", response_model=StrategyApprovalTransition)
def reject_strategy(
    instance_id: str, payload: StrategyApprovalDecisionRequest
) -> StrategyApprovalTransition:
    """驳回：审核没通过或回测结论不可接受时落在这里，之后只能回到草稿重走流程。"""

    return _advance(
        instance_id,
        "rejected",
        payload.actor,
        evidence=payload.evidence,
        note=payload.note,
    )


@approval_router.post(
    "/approvals/{instance_id}/live-authorization",
    response_model=StrategyApprovalTransition,
)
def authorize_live_trading(
    instance_id: str, payload: LiveAuthorizationRequest
) -> StrategyApprovalTransition:
    """实盘授权：记录授权事实，不打开实盘开关（开关属于执行域）。"""

    _require_positive_budget(payload.capital_budget)
    return _advance(
        instance_id,
        "live_authorized",
        payload.actor,
        evidence=payload.evidence,
        note=payload.note,
    )


def _advance(
    instance_id: str,
    target: str,
    actor: str,
    *,
    evidence: str | None = None,
    note: str | None = None,
) -> StrategyApprovalTransition:
    """读出实例再推进；实例不存在回 404，非法转移由状态机抛 400。

    推进的返回值是推进后的实例（阶段推进的语义是「实例变了」），响应要的是刚写下的那条
    记录，因此按写入顺序取该实例的最新一条。刚写完就取不到属于「不该发生」。
    """

    instance = get_instance(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"未找到策略实例 {instance_id}")
    advance(instance, target, actor, evidence, note=note)
    record = latest_transition(instance_id)
    if record is None:  # 同一事务里刚写过这一行, 读不到属于「不该发生」
        raise InvariantViolation(f"策略实例 {instance_id} 推进后没有审批记录")
    return _transition(record)


def _require_positive_budget(value: str) -> None:
    """授权必须带一个为正的资金预算；非正数的授权没有实际含义。"""

    try:
        budget = Decimal(value)
    except InvalidOperation:  # 契约的字符串模式已经拦了大部分, 这里只兜住不可能的值
        raise ValidationError(f"资金预算不是合法数字:{value!r}") from None
    if budget <= 0:
        raise ValidationError(f"资金预算必须为正数:{value}")


def _transition(record: ApprovalTransition) -> StrategyApprovalTransition:
    """域审批记录 → 契约模型。"""

    return StrategyApprovalTransition(
        approval_id=record.approval_id,
        instance_id=record.instance_id,
        from_status=record.from_status,
        to_status=record.to_status,
        actor=record.actor,
        at=record.at,
        note=record.note,
        evidence=record.evidence,
    )

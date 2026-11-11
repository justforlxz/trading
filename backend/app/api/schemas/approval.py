"""策略审批契约：八阶段生命周期的推进记录、审核决定与实盘授权。

生命周期见 `docs/prd/v2.md` §三.5 与 `docs/prd/decisions.md` D7；每次推进写一条
记录，`from_status` 与 `to_status` 都取自 `StrategyStatus`，因此「从哪来、到哪去」
可用取值集合直接校验。

实盘授权只记录授权事实，不打开实盘开关（开关属于执行域）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import DecimalString, StrategyStatus, UtcDatetime

__all__ = [
    "LiveAuthorizationRequest",
    "StrategyApprovalDecisionRequest",
    "StrategyApprovalListResponse",
    "StrategyApprovalRequest",
    "StrategyApprovalTransition",
]


_EXAMPLE_TRANSITION = {
    "approval_id": "apr_0001",
    "instance_id": "si_0001",
    "from_status": "strategy_generation",
    "to_status": "pending_review",
    "actor": "lxz",
    "at": "2026-11-10T07:10:00Z",
    "note": "提交人工审核",
    "evidence": None,
}


class StrategyApprovalTransition(BaseModel):
    """一次状态推进记录。

    `from_status` 为 `null` 表示该实例的第一条记录（从「已生成」进入审核）。
    `evidence` 是推进依据的引用，例如量化验证的达标报告编号；没有依据的推进留空。
    """

    approval_id: str
    instance_id: str
    from_status: StrategyStatus | None = None
    to_status: StrategyStatus
    actor: str
    at: UtcDatetime
    note: str | None = None
    evidence: str | None = None

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_TRANSITION]})


class StrategyApprovalListResponse(BaseModel):
    items: list[StrategyApprovalTransition]
    total: int

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [_EXAMPLE_TRANSITION], "total": 1}]}
    )


class StrategyApprovalRequest(BaseModel):
    """提交人工审核：策略实例从「已生成」进入待审核，不改策略配置。"""

    instance_id: str
    actor: str
    note: str | None = None


class StrategyApprovalDecisionRequest(BaseModel):
    """审核决定：通过或驳回。驳回只能回到 `strategy_generation`。"""

    actor: str
    note: str | None = None
    evidence: str | None = None


class LiveAuthorizationRequest(BaseModel):
    """申请实盘授权：记录授权人与已批准的资金预算，不打开实盘开关。"""

    actor: str
    capital_budget: DecimalString
    note: str | None = None
    evidence: str | None = None

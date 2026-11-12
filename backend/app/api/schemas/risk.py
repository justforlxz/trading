"""风险事件契约：列表与标记已处置。

事件记录风控拒绝了哪条规则、哪个实例与标的以及触发原因；分级处置在同一张表上
追加严重程度、动作、处置目标与被覆盖的组合申请。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import UtcDatetime

__all__ = ["RiskEvent", "RiskEventListResponse"]


_EXAMPLE_EVENT = {
    "event_id": "re_3f2a9c1d",
    "instance_id": "si_0001",
    "inst_id": "XAAPL-USDT",
    "rule": "order_amount_ratio",
    "detail": "单笔金额 3000 超过组合权益的 0.20, 上限 2000",
    "created_at": "2026-11-13T02:00:00Z",
    "resolved_at": None,
    "severity": "light",
    "action": "warn",
    "target_product_key": "AAPL",
    "overridden_approval_id": None,
}


class RiskEvent(BaseModel):
    event_id: str
    instance_id: str | None = None
    inst_id: str | None = None
    rule: str
    detail: str
    created_at: UtcDatetime
    resolved_at: UtcDatetime | None = None
    severity: str | None = None
    action: str | None = None
    target_product_key: str | None = None
    overridden_approval_id: str | None = None

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_EVENT]})


class RiskEventListResponse(BaseModel):
    items: list[RiskEvent]
    total: int

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [_EXAMPLE_EVENT], "total": 1}]}
    )

"""机会发现契约：目标驱动与市场驱动的候选机会、候选腿与状态流转。

目标驱动的锚点 `anchor_product_key` 只是分析锚点，**不要求**出现在 `legs` 里：
锚点自身没有信号时，机会由它的关联标的组成。

状态流转只允许 `new → reviewed → adopted | rejected`，以及 `new | reviewed → expired`；
非法流转由领域层拒绝，契约只给出取值集合。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import (
    DecimalString,
    InstType,
    PositionSide,
    UtcDatetime,
)

__all__ = [
    "Opportunity",
    "OpportunityLeg",
    "OpportunityListResponse",
    "OpportunityMode",
    "OpportunityStatus",
    "OpportunityStatusUpdateRequest",
]

OpportunityMode = Literal["target", "market"]
OpportunityStatus = Literal["new", "reviewed", "adopted", "rejected", "expired"]


class OpportunityLeg(BaseModel):
    """候选腿：某个标的方向与得分。目标权重由 T3.5 的组合生成阶段给出。"""

    inst_id: str
    inst_type: InstType
    product_key: str
    direction: PositionSide
    score: DecimalString


_EXAMPLE_LEGS = [
    {
        "inst_id": "MSFT-USDT-SWAP",
        "inst_type": "SWAP",
        "product_key": "MSFT",
        "direction": "long",
        "score": "0.82",
    },
    {
        "inst_id": "NVDA-USDT-SWAP",
        "inst_type": "SWAP",
        "product_key": "NVDA",
        "direction": "short",
        "score": "0.71",
    },
]

_EXAMPLE_OPPORTUNITY = {
    "opportunity_id": "opp_0001",
    "mode": "target",
    "anchor_product_key": "AAPL",
    "as_of": "2026-11-10T00:00:00Z",
    "score": "0.78",
    "legs": _EXAMPLE_LEGS,
    "evidence": '{"correlation":0.87,"breadth":0.8,"resonance":0.62}',
    "status": "new",
}


class Opportunity(BaseModel):
    """一条机会记录。

    `evidence` 是判定依据的 JSON 文本（相关系数、广度、共振强度等），原样透传，
    不在契约层二次解释；`score` 是筛选用的综合分数。
    """

    opportunity_id: str
    mode: OpportunityMode
    anchor_product_key: str | None = None
    as_of: UtcDatetime
    score: DecimalString
    legs: list[OpportunityLeg]
    evidence: str
    status: OpportunityStatus

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_OPPORTUNITY]})


class OpportunityListResponse(BaseModel):
    items: list[Opportunity]
    total: int

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [_EXAMPLE_OPPORTUNITY], "total": 1}]}
    )


class OpportunityStatusUpdateRequest(BaseModel):
    """状态变更请求：目标状态必须是取值集合内、且是 `status` 允许的下一步。"""

    status: OpportunityStatus

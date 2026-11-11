"""机会发现端点：列表、详情与状态流转。

端点只做入参校验与响应组装；评分、落库与状态机都在 `app.opportunity` 里。
域层用 `None` 表示「没有这条机会」，这一层再翻译成 404；非法状态转移由
`ValidationError` 统一翻译成 400，端点自己不再判断一次。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app import opportunity
from app.api.mapping import decimal_str
from app.api.schemas import (
    Opportunity,
    OpportunityLeg,
    OpportunityListResponse,
    OpportunityMode,
    OpportunityStatus,
    OpportunityStatusUpdateRequest,
)
from app.opportunity import OpportunityRecord

__all__ = ["opportunity_router"]

opportunity_router = APIRouter(tags=["opportunity"])


@opportunity_router.get("/opportunities", response_model=OpportunityListResponse)
def list_opportunities(
    mode: OpportunityMode | None = Query(None),
    anchor_product_key: str | None = Query(None),
    status: OpportunityStatus | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> OpportunityListResponse:
    records, total = opportunity.list_opportunities(
        mode=mode,
        anchor_product_key=anchor_product_key,
        status=status,
        limit=limit,
    )
    return OpportunityListResponse(items=[_opportunity(row) for row in records], total=total)


@opportunity_router.get("/opportunities/{opportunity_id}", response_model=Opportunity)
def get_opportunity(opportunity_id: str) -> Opportunity:
    record = opportunity.get_opportunity(opportunity_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到机会 {opportunity_id}")
    return _opportunity(record)


@opportunity_router.patch("/opportunities/{opportunity_id}", response_model=Opportunity)
def update_opportunity_status(
    opportunity_id: str, payload: OpportunityStatusUpdateRequest
) -> Opportunity:
    record = opportunity.set_status(opportunity_id, payload.status)
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到机会 {opportunity_id}")
    return _opportunity(record)


def _opportunity(record: OpportunityRecord) -> Opportunity:
    """域记录 → 契约模型：分数以十进制字符串出接口，`evidence` 原样透传。"""

    return Opportunity(
        opportunity_id=record.opportunity_id,
        mode=record.mode,
        anchor_product_key=record.anchor_product_key,
        as_of=record.as_of,
        score=decimal_str(record.score),
        legs=[
            OpportunityLeg(
                inst_id=leg.inst_id,
                inst_type=leg.inst_type,
                product_key=leg.product_key,
                direction=leg.direction,
                score=decimal_str(leg.score),
            )
            for leg in record.legs
        ],
        evidence=record.evidence,
        status=record.status,
    )

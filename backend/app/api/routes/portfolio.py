"""组合管理端点：组合列表、单策略明细、全局敞口、调整申请与批准。

端点只做入参校验与响应组装：账本、FIFO 核算、冲突检测与敞口公式都在
`app.portfolio` 里。批准的语义是「申请从 pending 变成 approved，同时目标写进生效
分配」；未批准的申请不进入生效状态。
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query

from app.api.mapping import decimal_str
from app.api.schemas import (
    ExposureOverviewResponse,
    PortfolioAdjustment,
    PortfolioAdjustmentCreateRequest,
    PortfolioAdjustmentDecisionRequest,
    PortfolioAdjustmentListResponse,
    PortfolioConflict,
    StrategyPortfolio,
    StrategyPortfolioDetailResponse,
    StrategyPortfolioListResponse,
    TargetLeg,
    TargetPortfolio,
    VirtualPosition,
)
from app.portfolio import (
    AdjustmentRecord,
    ExposureOverview,
    StrategyPortfolioDetail,
    TargetLegRecord,
    TargetRecord,
    create_adjustment,
    decide_adjustment,
    exposure_overview,
    get_portfolio,
    list_adjustments,
    list_portfolios,
)
from app.portfolio import (
    StrategyPortfolio as PortfolioRecord,
)
from app.portfolio import (
    VirtualPosition as PositionRecord,
)

__all__ = ["portfolio_router"]

portfolio_router = APIRouter(tags=["portfolio"])


@portfolio_router.get("/portfolio/strategies", response_model=StrategyPortfolioListResponse)
def list_strategy_portfolios() -> StrategyPortfolioListResponse:
    rows, total = list_portfolios()
    return StrategyPortfolioListResponse(items=[_portfolio(row) for row in rows], total=total)


@portfolio_router.get(
    "/portfolio/strategies/{instance_id}", response_model=StrategyPortfolioDetailResponse
)
def get_strategy_portfolio(instance_id: str) -> StrategyPortfolioDetailResponse:
    detail = get_portfolio(instance_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"未找到策略实例 {instance_id}")
    return _detail(detail)


@portfolio_router.get("/portfolio/exposure", response_model=ExposureOverviewResponse)
def get_portfolio_exposure() -> ExposureOverviewResponse:
    overview: ExposureOverview = exposure_overview()
    return ExposureOverviewResponse(
        gross_exposure=decimal_str(overview.gross_exposure),
        net_exposure=decimal_str(overview.net_exposure),
        long_exposure=decimal_str(overview.long_exposure),
        short_exposure=decimal_str(overview.short_exposure),
        largest_position_share=decimal_str(overview.largest_position_share),
        open_positions=overview.open_positions,
        product_count=overview.product_count,
        conflicts=[
            PortfolioConflict(
                product_key=item.product_key,
                long_instance_ids=list(item.long_instance_ids),
                short_instance_ids=list(item.short_instance_ids),
            )
            for item in overview.conflicts
        ],
        generated_at=overview.generated_at,
    )


@portfolio_router.get("/portfolio/adjustments", response_model=PortfolioAdjustmentListResponse)
def list_portfolio_adjustments(
    limit: int = Query(200, ge=1, le=500),
) -> PortfolioAdjustmentListResponse:
    rows, total = list_adjustments(limit=limit)
    return PortfolioAdjustmentListResponse(items=[_adjustment(row) for row in rows], total=total)


@portfolio_router.post(
    "/portfolio/adjustments", response_model=PortfolioAdjustment, status_code=201
)
def create_portfolio_adjustment(
    payload: PortfolioAdjustmentCreateRequest,
) -> PortfolioAdjustment:
    """提交调整申请：只落 `pending`，不写生效目标。"""

    return _adjustment(
        create_adjustment(
            instance_id=payload.instance_id,
            requested_by=payload.requested_by,
            target=_target(payload.target),
            note=payload.note,
        )
    )


@portfolio_router.patch(
    "/portfolio/adjustments/{adjustment_id}", response_model=PortfolioAdjustment
)
def decide_portfolio_adjustment(
    adjustment_id: str, payload: PortfolioAdjustmentDecisionRequest
) -> PortfolioAdjustment:
    """批准或驳回；`approved` 才会把目标写进生效分配。"""

    record = decide_adjustment(
        adjustment_id,
        decision=payload.decision,
        decided_by=payload.decided_by,
        note=payload.note,
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到调整申请 {adjustment_id}")
    return _adjustment(record)


def _portfolio(row: PortfolioRecord) -> StrategyPortfolio:
    return StrategyPortfolio(
        instance_id=row.instance_id,
        strategy_id=row.strategy_id,
        name=row.name,
        lifecycle_status=row.lifecycle_status,
        priority=row.priority,
        capital_budget=decimal_str(row.capital_budget),
        gross_exposure=decimal_str(row.gross_exposure),
        net_exposure=decimal_str(row.net_exposure),
        unrealized_pnl=decimal_str(row.unrealized_pnl),
        realized_pnl=decimal_str(row.realized_pnl),
        open_positions=row.open_positions,
    )


def _position(row: PositionRecord) -> VirtualPosition:
    return VirtualPosition(
        inst_id=row.inst_id,
        inst_type=row.inst_type,
        product_key=row.product_key,
        direction=row.direction,
        qty=decimal_str(row.qty),
        unit=row.unit,
        avg_cost=decimal_str(row.avg_cost),
        mark_price=decimal_str(row.mark_price),
        notional=decimal_str(row.notional),
        unrealized_pnl=decimal_str(row.unrealized_pnl),
        opened_at=row.opened_at,
    )


def _target(target: TargetPortfolio) -> TargetRecord:
    legs = tuple(
        TargetLegRecord(
            inst_id=leg.inst_id,
            inst_type=leg.inst_type,
            direction=leg.direction,
            target_weight=Decimal(leg.target_weight),
            qty=None if leg.qty is None else Decimal(leg.qty),
            unit=leg.unit,
        )
        for leg in target.legs
    )
    return TargetRecord(legs=legs, net_exposure=Decimal(target.net_exposure))


def _target_model(target: TargetRecord) -> TargetPortfolio:
    return TargetPortfolio(
        legs=[
            TargetLeg(
                inst_id=leg.inst_id,
                inst_type=leg.inst_type,
                direction=leg.direction,
                target_weight=decimal_str(leg.target_weight),
                qty=None if leg.qty is None else decimal_str(leg.qty),
                unit=leg.unit,
            )
            for leg in target.legs
        ],
        net_exposure=decimal_str(target.net_exposure),
    )


def _detail(detail: StrategyPortfolioDetail) -> StrategyPortfolioDetailResponse:
    return StrategyPortfolioDetailResponse(
        portfolio=_portfolio(detail.portfolio),
        positions=[_position(row) for row in detail.positions],
        target=None if detail.target is None else _target_model(detail.target),
    )


def _adjustment(row: AdjustmentRecord) -> PortfolioAdjustment:
    return PortfolioAdjustment(
        adjustment_id=row.adjustment_id,
        instance_id=row.instance_id,
        status=row.status,
        requested_by=row.requested_by,
        requested_at=row.requested_at,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        note=row.note,
        target=_target_model(row.target),
    )

"""组合管理契约：全局敞口、策略级虚拟持仓、重复持仓与多空冲突、调整申请。

成员、方向、目标权重的变更只能通过**申请**完成：申请先落 `pending`，批准后才生效，
记录里同时留下申请人、批准人与时间（PRD §三.11）。

虚拟持仓与真实持仓分开：这里是策略自己的账本，真实账户的持仓与订单见
`app/api/schemas/trades.py`。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import (
    DecimalString,
    InstType,
    PositionSide,
    QtyUnit,
    StrategyStatus,
    TargetPortfolio,
    UtcDatetime,
)

__all__ = [
    "AdjustmentDecision",
    "AdjustmentStatus",
    "ExposureOverviewResponse",
    "PortfolioAdjustment",
    "PortfolioAdjustmentCreateRequest",
    "PortfolioAdjustmentDecisionRequest",
    "PortfolioAdjustmentListResponse",
    "PortfolioConflict",
    "StrategyPortfolio",
    "StrategyPortfolioDetailResponse",
    "StrategyPortfolioListResponse",
    "VirtualPosition",
]

AdjustmentStatus = Literal["pending", "approved", "rejected"]
AdjustmentDecision = Literal["approved", "rejected"]


class StrategyPortfolio(BaseModel):
    """一个策略实例的资金与敞口概览（组合列表的一行）。

    `priority` 越大越优先；`capital_budget` 是已批准给该策略的资金预算。
    """

    instance_id: str
    strategy_id: str
    name: str
    lifecycle_status: StrategyStatus
    priority: int
    capital_budget: DecimalString
    gross_exposure: DecimalString
    net_exposure: DecimalString
    unrealized_pnl: DecimalString
    realized_pnl: DecimalString
    open_positions: int


class VirtualPosition(BaseModel):
    """策略账本里的一条持仓；`avg_cost` 是当前剩余持仓的成本价（FIFO 核算后）。"""

    inst_id: str
    inst_type: InstType
    product_key: str
    direction: PositionSide
    qty: DecimalString
    unit: QtyUnit
    avg_cost: DecimalString
    mark_price: DecimalString
    notional: DecimalString
    unrealized_pnl: DecimalString
    opened_at: UtcDatetime


_EXAMPLE_PORTFOLIO = {
    "instance_id": "si_0001",
    "strategy_id": "ma_cross",
    "name": "AAPL 均线趋势",
    "lifecycle_status": "live_running",
    "priority": 10,
    "capital_budget": "2000.00",
    "gross_exposure": "1997.15",
    "net_exposure": "1997.15",
    "unrealized_pnl": "28.64",
    "realized_pnl": "12.05",
    "open_positions": 1,
}

_EXAMPLE_POSITION = {
    "inst_id": "XAAPL-USDT",
    "inst_type": "SPOT",
    "product_key": "AAPL",
    "direction": "long",
    "qty": "8.63",
    "unit": "base",
    "avg_cost": "228.10",
    "mark_price": "231.42",
    "notional": "1997.15",
    "unrealized_pnl": "28.64",
    "opened_at": "2026-11-09T14:00:00Z",
}

_EXAMPLE_TARGET = {
    "legs": [
        {
            "inst_id": "XAAPL-USDT",
            "inst_type": "SPOT",
            "direction": "long",
            "target_weight": "0.25",
            "qty": "8.63",
            "unit": "base",
        }
    ],
    "net_exposure": "0.25",
}


class StrategyPortfolioListResponse(BaseModel):
    items: list[StrategyPortfolio]
    total: int

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [_EXAMPLE_PORTFOLIO], "total": 1}]}
    )


class StrategyPortfolioDetailResponse(BaseModel):
    """单个策略的明细：资金与敞口、虚拟持仓、当前生效的目标组合（尚未生成时为 `null`）。"""

    portfolio: StrategyPortfolio
    positions: list[VirtualPosition]
    target: TargetPortfolio | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "portfolio": _EXAMPLE_PORTFOLIO,
                    "positions": [_EXAMPLE_POSITION],
                    "target": _EXAMPLE_TARGET,
                }
            ]
        }
    )


class PortfolioConflict(BaseModel):
    """同一 `product_key` 在多个策略上方向相反；两侧策略都要列出，不合并成一条。"""

    product_key: str
    long_instance_ids: list[str]
    short_instance_ids: list[str]


class ExposureOverviewResponse(BaseModel):
    """全局敞口总览。`largest_position_share` 是单一标的最大权重占组合权益的比例。"""

    gross_exposure: DecimalString
    net_exposure: DecimalString
    long_exposure: DecimalString
    short_exposure: DecimalString
    largest_position_share: DecimalString
    open_positions: int
    product_count: int
    conflicts: list[PortfolioConflict]
    generated_at: UtcDatetime

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "gross_exposure": "3510.40",
                    "net_exposure": "1997.15",
                    "long_exposure": "2753.78",
                    "short_exposure": "756.62",
                    "largest_position_share": "0.24",
                    "open_positions": 3,
                    "product_count": 2,
                    "conflicts": [
                        {
                            "product_key": "AAPL",
                            "long_instance_ids": ["si_0001"],
                            "short_instance_ids": ["si_0002"],
                        }
                    ],
                    "generated_at": "2026-11-10T08:00:00Z",
                }
            ]
        }
    )


_EXAMPLE_ADJUSTMENT = {
    "adjustment_id": "adj_0001",
    "instance_id": "si_0001",
    "status": "pending",
    "requested_by": "lxz",
    "requested_at": "2026-11-10T07:30:00Z",
    "decided_by": None,
    "decided_at": None,
    "note": "把 AAPL 目标权重从 0.25 提到 0.30",
    "target": _EXAMPLE_TARGET,
}


class PortfolioAdjustment(BaseModel):
    """一条组合调整申请；批准之前 `target` 不生效。"""

    adjustment_id: str
    instance_id: str
    status: AdjustmentStatus
    requested_by: str
    requested_at: UtcDatetime
    decided_by: str | None = None
    decided_at: UtcDatetime | None = None
    note: str | None = None
    target: TargetPortfolio

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_ADJUSTMENT]})


class PortfolioAdjustmentListResponse(BaseModel):
    items: list[PortfolioAdjustment]
    total: int

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [_EXAMPLE_ADJUSTMENT], "total": 1}]}
    )


class PortfolioAdjustmentCreateRequest(BaseModel):
    """提交调整申请：只写申请，不改生效状态。"""

    instance_id: str
    requested_by: str
    target: TargetPortfolio
    note: str | None = None


class PortfolioAdjustmentDecisionRequest(BaseModel):
    """批准或驳回一条申请；决定必须由人工作出。"""

    decision: AdjustmentDecision
    decided_by: str
    note: str | None = None

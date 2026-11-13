"""全局组合管理：策略级虚拟持仓、FIFO 成本、资金分配、敞口与调整申请（P2）。

门面即出口：跨包只允许 `from app.portfolio import ...`。
"""

from app.portfolio.conflict import (
    ExposureLeg,
    aggregate_exposure,
    net_exposure,
    product_conflicts,
)
from app.portfolio.ledger import (
    BUY,
    SELL,
    LedgerPosition,
    Lot,
    apply_fill,
    unrealized_pnl,
)
from app.portfolio.model import (
    AllocationRow,
    PortfolioAdjustmentRow,
    VirtualFillRow,
    VirtualPositionRow,
)
from app.portfolio.service import (
    PENDING,
    SUPERSEDED,
    StrategyPortfolio,
    TargetLegRecord,
    TargetRecord,
    create_adjustment,
    decide_adjustment,
    exposure_overview,
    get_portfolio,
    list_adjustments,
    list_portfolios,
    record_allocation,
    record_fill,
)

__all__ = [
    "BUY",
    "PENDING",
    "SELL",
    "SUPERSEDED",
    "AllocationRow",
    "ExposureLeg",
    "LedgerPosition",
    "Lot",
    "PortfolioAdjustmentRow",
    "StrategyPortfolio",
    "TargetLegRecord",
    "TargetRecord",
    "VirtualFillRow",
    "VirtualPositionRow",
    "aggregate_exposure",
    "apply_fill",
    "create_adjustment",
    "decide_adjustment",
    "exposure_overview",
    "get_portfolio",
    "list_adjustments",
    "list_portfolios",
    "net_exposure",
    "product_conflicts",
    "record_allocation",
    "record_fill",
    "unrealized_pnl",
]

"""交易执行：订单状态机、账户实际持仓、paper 撮合与 Manual 模式编排（P3）。

门面即出口：跨包只允许 `from app.execution import ...`。

T5.2 提供订单状态机、账户实际持仓与 paper 撮合；T5.3 在它们之上提供交易计划、
人工确认、下单编排与订单/持仓同步。策略级虚拟持仓（每个策略实例自己的成本与盈亏）
属于全局组合管理（T7.1），不在这里建第二套账，也不做对账恢复（T6.3）。
"""

from __future__ import annotations

from app.execution.errors import PaperRejected
from app.execution.manual import (
    build_plan,
    client_order_id,
    confirm,
    plan_digest,
    require_confirmation,
)
from app.execution.model import (
    ConfirmationRecord,
    ExecutionState,
    Placement,
    PlacementResult,
    PlanLeg,
    SyncResult,
    TradePlan,
    VenueSnapshot,
)
from app.execution.orders import (
    LEGAL_TRANSITIONS,
    ORDER_STATUSES,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_FILLED,
    STATUS_OPEN,
    STATUS_PARTIALLY_FILLED,
    STATUS_PENDING,
    TERMINAL_STATUSES,
    Order,
    accept,
    apply_fill,
    cancel,
    fail,
    from_venue_order,
    new_order,
    require_transition,
)
from app.execution.paper import PaperBroker
from app.execution.positions import (
    NET_POS_SIDE,
    SIDE_LONG,
    SIDE_SHORT,
    AccountPosition,
    PositionBook,
    from_venue_position,
)
from app.execution.service import (
    ExecutionService,
    OrderBackend,
    PaperOrderBackend,
    TradePortBackend,
    paper_snapshot,
)
from app.execution.sync import sync_state

__all__ = [
    "LEGAL_TRANSITIONS",
    "NET_POS_SIDE",
    "ORDER_STATUSES",
    "SIDE_LONG",
    "SIDE_SHORT",
    "STATUS_CANCELLED",
    "STATUS_FAILED",
    "STATUS_FILLED",
    "STATUS_OPEN",
    "STATUS_PARTIALLY_FILLED",
    "STATUS_PENDING",
    "TERMINAL_STATUSES",
    "AccountPosition",
    "ConfirmationRecord",
    "ExecutionService",
    "ExecutionState",
    "Order",
    "OrderBackend",
    "PaperBroker",
    "PaperOrderBackend",
    "PaperRejected",
    "Placement",
    "PlacementResult",
    "PlanLeg",
    "PositionBook",
    "SyncResult",
    "TradePlan",
    "TradePortBackend",
    "VenueSnapshot",
    "accept",
    "apply_fill",
    "build_plan",
    "cancel",
    "client_order_id",
    "confirm",
    "fail",
    "from_venue_order",
    "from_venue_position",
    "new_order",
    "paper_snapshot",
    "plan_digest",
    "require_confirmation",
    "require_transition",
    "sync_state",
]

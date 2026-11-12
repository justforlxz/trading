"""交易执行：订单状态机、账户实际持仓与 paper 撮合（P3，真实交易默认关闭）。

门面即出口：跨包只允许 `from app.execution import ...`。

本节点（T5.2）只做**账户实际持仓**这一层。策略级虚拟持仓（每个策略实例自己的成本与
盈亏）属于全局组合管理（T7.1），不在这里建第二套账，也不做对账恢复（T6.3）。
"""

from __future__ import annotations

from app.execution.errors import PaperRejected
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
    "Order",
    "PaperBroker",
    "PaperRejected",
    "PositionBook",
    "accept",
    "apply_fill",
    "cancel",
    "fail",
    "from_venue_order",
    "from_venue_position",
    "new_order",
    "require_transition",
]

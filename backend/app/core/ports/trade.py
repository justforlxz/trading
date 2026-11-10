"""交易端口。

下单、撤单、查单，以及查询资金与持仓。执行层是唯一持有账户凭据的地方，其余模块
只能通过本协议间接交易。

实现约定：交易所明确拒单抛 `ExecutionRejected`，风控拒绝抛 `RiskBlocked`，上游
故障抛 `UpstreamError` 的子类；传参不合法抛 `ValidationError`。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from app.core.types import Money, OrderIntent

__all__ = ["Fill", "Order", "Position", "TradePort"]


@dataclass(frozen=True, slots=True)
class Order:
    """交易所侧的一张订单。`status` 保留上游状态字面量，由执行层做语义映射。"""

    order_id: str
    client_order_id: str
    inst_id: str
    side: str
    order_type: str
    qty: Decimal
    price: Decimal | None
    filled_qty: Decimal
    status: str
    ts: datetime


@dataclass(frozen=True, slots=True)
class Fill:
    """一次成交。手续费按实际扣费币种记账，因此是 `Money` 而不是裸数值。"""

    fill_id: str
    order_id: str
    inst_id: str
    side: str
    qty: Decimal
    price: Decimal
    fee: Money
    ts: datetime


@dataclass(frozen=True, slots=True)
class Position:
    """当前持仓。`qty` 带符号：正为多、负为空。"""

    inst_id: str
    qty: Decimal
    avg_price: Decimal
    unrealized_pnl: Money


@runtime_checkable
class TradePort(Protocol):
    """交易端口：业务模块只依赖这些方法签名。

    方法体一律 `raise NotImplementedError`：继承本协议却不实现某个方法是装配错误，
    应该在第一次调用时立刻暴露，而不是返回 None 让错误流到下游。
    """

    def balance(self, currency: str = "USDT") -> Money:
        """返回指定币种的可用余额。"""

        raise NotImplementedError

    def positions(self) -> list[Position]:
        """返回当前持仓（无持仓的标的不出现）。"""

        raise NotImplementedError

    def place(self, intent: OrderIntent) -> Order:
        """按意图下单，返回交易所确认后的订单。"""

        raise NotImplementedError

    def cancel(self, inst_id: str, order_id: str) -> None:
        """撤单；订单已终结时抛 `ExecutionRejected`。"""

        raise NotImplementedError

    def order(self, inst_id: str, order_id: str) -> Order:
        """按订单号查询订单。"""

        raise NotImplementedError

    def fills(self, inst_id: str, order_id: str | None = None) -> list[Fill]:
        """查询成交记录；`order_id` 为空时返回该标的的全部成交。"""

        raise NotImplementedError

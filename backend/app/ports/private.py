"""交易私有接口的端口定义（Protocol + 归一化 DTO）。

分层约定与 `ports/market_data.py` 相同：适配器负责把交易所原始 JSON 归一化成
这里的冻结 dataclass，原始字段不越过这一层；编排层只依赖本文件里的 Protocol。

模拟（paper）与实盘（real）共用同一套 DTO 与同一套订单生命周期，差别只在
`PrivateTradingSource` 的实现（本地撮合 vs OKX 私有 REST）。
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """一笔待提交订单的归一化入参。"""

    inst_id: str
    side: str  # buy / sell
    position_side: str  # long / short
    order_type: str  # market / limit
    quantity: Decimal
    price: Decimal | None
    client_order_id: str
    reduce_only: bool = False


@dataclass(frozen=True, slots=True)
class OrderAck:
    """交易所受理结果；只表示「已受理」，不代表成交。"""

    client_order_id: str
    exchange_order_id: str
    state: str  # submitted
    code: str


@dataclass(frozen=True, slots=True)
class ExchangeOrder:
    """交易所侧订单快照。`state` 已归一化为本项目状态机的取值。"""

    client_order_id: str
    exchange_order_id: str
    inst_id: str
    side: str
    position_side: str
    state: str  # submitted / partial / filled / canceled / rejected
    quantity: Decimal
    filled_quantity: Decimal
    average_price: Decimal
    fee: Decimal
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ExchangeFill:
    """一笔成交。`fill_id` 在同一个交易所订单内唯一，用于幂等落库。"""

    fill_id: str
    client_order_id: str | None
    exchange_order_id: str
    inst_id: str
    side: str
    position_side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    fee_currency: str
    filled_at: datetime


@dataclass(frozen=True, slots=True)
class ExchangePosition:
    """交易所侧持仓（已按 long/short 拆分，数量非负）。"""

    inst_id: str
    position_side: str
    quantity: Decimal
    average_price: Decimal
    unrealized_pnl: Decimal


@dataclass(frozen=True, slots=True)
class AccountBalance:
    """账户权益快照（统一折算 USDT）。"""

    total_equity: Decimal
    available_equity: Decimal
    currency: str


class PrivateTradingSource(Protocol):
    """私有交易接口：下单、撤单、查单、成交、持仓、账户。"""

    async def place_order(self, request: OrderRequest) -> OrderAck: ...

    async def cancel_order(
        self,
        *,
        inst_id: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> None: ...

    async def fetch_order(
        self,
        *,
        inst_id: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> ExchangeOrder | None: ...

    async def list_open_orders(self, *, inst_id: str | None = None) -> list[ExchangeOrder]: ...

    async def fetch_fills(
        self, *, inst_id: str | None = None, since: datetime | None = None
    ) -> list[ExchangeFill]: ...

    async def fetch_positions(self) -> list[ExchangePosition]: ...

    async def fetch_balance(self) -> AccountBalance: ...


__all__ = [
    "AccountBalance",
    "ExchangeFill",
    "ExchangeOrder",
    "ExchangePosition",
    "OrderAck",
    "OrderRequest",
    "PrivateTradingSource",
]

"""端口定义：跨模块协作的唯一横向契约。

端口按能力拆分（行情 / 交易），不按上游厂商拆分——同一个端口可以有多个实现，
实现之间靠注册名区分。
"""

from __future__ import annotations

from app.core.ports.market_data import MarketDataPort, Ticker
from app.core.ports.trade import (
    AccountSnapshot,
    ExchangePosition,
    Fill,
    Order,
    Position,
    TradePort,
)

__all__ = [
    "AccountSnapshot",
    "ExchangePosition",
    "Fill",
    "MarketDataPort",
    "Order",
    "Position",
    "Ticker",
    "TradePort",
]

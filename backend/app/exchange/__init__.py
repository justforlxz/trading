"""交易所适配层门面。

本包是行情端口与交易端口的**实现方**：端口与值对象定义在 `app.core`，这里只发布
「怎么连上游」——客户端、各来源实现、装配函数，以及适配层自己的异常类型。业务模块
依赖 `app.core` 的端口，不依赖本包的实现细节。

下单意图的幂等键表（`OrderSubmission`）也在这里发布：它是业务表，需要被装配根
导入一次才会进 `Base.metadata`。

本包只发布 OKX 的公开行情与私有交易实现。
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.exchange.errors import ExchangeError, RateLimitedError
from app.exchange.okx.client import OkxClient
from app.exchange.okx.ledger import OrderSubmission
from app.exchange.okx.market import OkxMarketData, TickerQuote
from app.exchange.okx.market_ws import (
    MarketPush,
    OkxPublicWebSocket,
    load_quote_snapshot,
)
from app.exchange.okx.private import OkxPrivateClient, create_trade_port
from app.exchange.okx.snapshots import (
    parse_account_snapshot_row,
    parse_exchange_position_row,
)
from app.exchange.okx.ws import OkxWebSocket

__all__ = [
    "ExchangeError",
    "MarketPush",
    "OkxClient",
    "OkxMarketData",
    "OkxPrivateClient",
    "OkxPublicWebSocket",
    "OkxWebSocket",
    "OrderSubmission",
    "RateLimitedError",
    "TickerQuote",
    "create_market_data",
    "create_trade_port",
    "load_quote_snapshot",
    "parse_account_snapshot_row",
    "parse_exchange_position_row",
]


def create_market_data(
    *,
    settings: Settings | None = None,
    transport: httpx.BaseTransport | None = None,
) -> OkxMarketData:
    """按进程配置装配默认行情实现。

    `transport` 供本地联调与测试注入自定义传输层；生产环境留空即走真实网络。
    """

    return OkxMarketData(OkxClient(settings=settings, transport=transport))

"""交易所适配层门面。

本包是行情端口的**实现方**：端口与值对象定义在 `app.core`，这里只发布「怎么连
交易所」——客户端、默认现货实现、装配函数，以及适配层自己的异常类型。
业务模块依赖 `app.core` 的端口，不依赖本包的实现细节。
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.exchange.errors import ExchangeError, RateLimitedError
from app.exchange.okx.client import OkxClient
from app.exchange.okx.market import OkxMarketData

__all__ = [
    "ExchangeError",
    "OkxClient",
    "OkxMarketData",
    "RateLimitedError",
    "create_market_data",
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

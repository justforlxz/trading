"""交易所适配层门面。

业务模块只通过这里拿行情：端口协议、中立数据结构、异常类型，以及默认的
OKX 现货实现。HTTP 细节（请求、限流、重试、字段名）全部留在本包内部。
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.exchange.errors import ExchangeError, RateLimitedError
from app.exchange.okx.client import OkxClient
from app.exchange.okx.market import OkxMarketData
from app.exchange.ports import Candle, InstrumentInfo, MarketDataPort, Ticker

__all__ = [
    "Candle",
    "ExchangeError",
    "InstrumentInfo",
    "MarketDataPort",
    "OkxClient",
    "OkxMarketData",
    "RateLimitedError",
    "Ticker",
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

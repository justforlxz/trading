"""非交易所的行情来源：一个来源一个模块，按名字登记在 `app.core.registry`。

`exchange/okx` 是交易所自己的公开接口；这里放的是「不是交易所」的行情来源。当前
只有美股代理（`us_equity_proxy`，正常交易时段的主行情源）。两者实现同一个
`MarketDataPort`，来源标识与 `candles.source` 同值：业务层按来源取数，不靠猜，也
不允许跨来源拼接。

门面只发布 `app.exchange` 顶层门面真正用到的两个名字；来源标识与周期能力留在
`us_equity` 模块自己的 `SOURCE` / `SUPPORTED_TIMEFRAMES`，等有使用方时再由那次
改动把名字发布到 `app.exchange` 的顶层门面。
"""

from app.exchange.providers.us_equity import (
    UsEquityMarketData,
    create_us_equity_market_data,
)

__all__ = [
    "UsEquityMarketData",
    "create_us_equity_market_data",
]

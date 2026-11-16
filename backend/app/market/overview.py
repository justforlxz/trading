"""OKX BTC 市场快照：最新价、24 小时涨跌、市场时段与报价时间。

市场概况只保留 BTC，数据直接来自 OKX 公共 ticker。这里没有外部 Provider、没有
Provider 注册表，也没有外部数据集同步：取不到行情时如实返回 `missing` 与原因，
不用旧值或演示值冒充实时数据。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.core import Clock, SystemClock, UpstreamError
from app.exchange import ExchangeError, OkxClient, OkxMarketData, TickerQuote
from app.market.session import SESSION_REGULAR

__all__ = [
    "MARKET_QUOTE_STALE_AFTER",
    "MarketOverviewItem",
    "MarketOverviewSnapshot",
    "btc_item_from_quote",
    "load_okx_btc",
    "market_overview_snapshot",
]

BTC_INST_ID = "BTC-USDT"
BTC_SOURCE = "okx_spot"
BTC_SYMBOL = "BTC"
BTC_NAME = "Bitcoin"
# 报价时间超过该阈值即视为过期，不能继续当作当前值。
MARKET_QUOTE_STALE_AFTER = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class MarketOverviewItem:
    symbol: str
    name: str
    value: Decimal | None
    change: Decimal | None
    change_pct: Decimal | None
    market_session: str
    source: str
    as_of: datetime | None
    is_delayed: bool
    quality_status: str
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class MarketOverviewSnapshot:
    as_of: datetime
    stale: bool
    stale_reason: str | None
    items: tuple[MarketOverviewItem, ...]


def _missing_item() -> MarketOverviewItem:
    return MarketOverviewItem(
        symbol=BTC_SYMBOL,
        name=BTC_NAME,
        value=None,
        change=None,
        change_pct=None,
        market_session=SESSION_REGULAR,
        source=BTC_SOURCE,
        as_of=None,
        is_delayed=False,
        quality_status="missing",
        source_url=None,
    )


def btc_item_from_quote(quote: TickerQuote) -> MarketOverviewItem:
    """把交易所适配层解析好的报价映射成市场概况项，不再解析上游字段。"""

    change = quote.last - quote.open_24h
    change_pct = (
        None if quote.open_24h == 0 else (change / quote.open_24h * 100).quantize(Decimal("0.01"))
    )
    return MarketOverviewItem(
        symbol=BTC_SYMBOL,
        name=BTC_NAME,
        value=quote.last,
        change=change,
        change_pct=change_pct,
        market_session=SESSION_REGULAR,
        source=BTC_SOURCE,
        as_of=quote.ts,
        is_delayed=False,
        quality_status="normal",
        source_url=None,
    )


def load_okx_btc() -> MarketOverviewItem:
    """BTC 现价与 24 小时涨跌，直接取 OKX 公共 ticker。"""

    with OkxClient() as client:
        quote = OkxMarketData(client).ticker_quote(BTC_INST_ID)
    return btc_item_from_quote(quote)


def _quality(item: MarketOverviewItem, now: datetime) -> str:
    """按报价时间与延迟标记决定质量；缺失与过期优先于延迟。"""

    if item.value is None or item.as_of is None:
        return "missing"
    if now - item.as_of > MARKET_QUOTE_STALE_AFTER:
        return "stale"
    if item.is_delayed:
        return "delayed"
    return "normal"


def market_overview_snapshot(
    *,
    btc_loader: Callable[[], MarketOverviewItem] | None = None,
    clock: Clock | None = None,
) -> MarketOverviewSnapshot:
    """BTC 的当前市场快照；取不到行情时给出 `missing` 与真实原因。"""

    now = (clock or SystemClock()).now()
    try:
        item = (btc_loader or load_okx_btc)()
    except (UpstreamError, ExchangeError) as exc:
        return MarketOverviewSnapshot(
            as_of=now,
            stale=True,
            stale_reason=f"OKX BTC 行情不可用: {exc}",
            items=(_missing_item(),),
        )

    quality = _quality(item, now)
    decorated = MarketOverviewItem(
        symbol=item.symbol,
        name=item.name,
        value=item.value,
        change=item.change,
        change_pct=item.change_pct,
        market_session=item.market_session,
        source=item.source,
        as_of=item.as_of,
        is_delayed=item.is_delayed,
        quality_status=quality,
        source_url=item.source_url,
    )
    stale_reason = None
    if quality == "stale":
        hours = int(MARKET_QUOTE_STALE_AFTER.total_seconds() // 3600)
        stale_reason = f"OKX BTC 报价时间已超过 {hours} 小时"
    elif quality == "missing":
        stale_reason = "OKX BTC 行情缺少数值或报价时间"
    return MarketOverviewSnapshot(
        as_of=now,
        stale=quality != "normal",
        stale_reason=stale_reason,
        items=(decorated,),
    )

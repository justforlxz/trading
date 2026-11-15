"""市场端点：五个市场指标、类别广度、宏观事件与新闻。

`/market/overview` 是 v6 的五个指标（NASDAQ、SP500、DOW、VIX、BTC），带来源、时间与
陈旧状态；`/market/breadth` 保留按 `SPOT` / `SWAP` 统计的涨跌家数与共振。两类标的的
交易时段不同，广度不能混成同一个横截面。

外部数据取不到时仍返回五个指标的位置，数值为 `null`、`quality_status=missing`，顶层
`stale` 为真；不用旧值冒充实时。事件时间同时给出 UTC 与北京时间展示字段。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from app.api.mapping import decimal_str
from app.api.providers import select_provider
from app.api.schemas import (
    MarketBreadth,
    MarketBreadthResponse,
    MarketEventItem,
    MarketEventListResponse,
    MarketOverviewItem,
    MarketResonance,
    MarketSnapshotResponse,
    NewsListResponse,
)
from app.api.schemas import (
    NewsItem as NewsItemSchema,
)
from app.api.schemas.common import Bar, InstType
from app.core import SystemClock
from app.market import (
    ExternalMarketOverview,
    MarketOverviewService,
    list_market_events,
    list_news,
    market_overview,
)
from app.market import (
    MarketOverviewItem as ExternalOverviewItem,
)

__all__ = ["market_router"]

market_router = APIRouter(tags=["market"])

# 契约的 DecimalString 只保证 12 位小数；8/3 这类比值是无限小数，出接口前必须量化。
_VALUE_QUANTUM = Decimal("1e-12")
BEIJING = timezone(timedelta(hours=8))
EVENT_LOOKBACK = timedelta(days=30)
EVENT_LOOKAHEAD = timedelta(days=90)


def _ratio_str(value: float | None) -> str | None:
    """比值 → 契约里的定点字符串；没有数时如实给 `null`，不补 0。"""

    if value is None:
        return None
    return decimal_str(Decimal(str(value)).quantize(_VALUE_QUANTUM, rounding=ROUND_HALF_UP))


def _market_overview() -> ExternalMarketOverview:
    """五个指标的当前快照；测试通过替换本函数注入 Provider。"""

    selection = select_provider()
    overview = MarketOverviewService(provider=selection.provider).overview()
    if selection.error is not None:
        overview = replace(
            overview,
            provider=selection.name,
            stale=True,
            stale_reason=selection.error,
        )
    return overview


def _overview_item(item: ExternalOverviewItem) -> MarketOverviewItem:
    return MarketOverviewItem(
        symbol=item.symbol,
        name=item.name,
        value=None if item.value is None else decimal_str(item.value),
        change=None if item.change is None else decimal_str(item.change),
        change_pct=None if item.change_pct is None else decimal_str(item.change_pct),
        market_session=item.market_session,
        source=item.source,
        as_of=item.as_of,
        is_delayed=item.is_delayed,
        quality_status=item.quality_status,
        source_url=item.source_url,
    )


@market_router.get("/market/overview", response_model=MarketSnapshotResponse)
def get_market_snapshot() -> MarketSnapshotResponse:
    """NASDAQ、SP500、DOW、VIX、BTC 的最新值、涨跌、时段与来源。"""

    overview = _market_overview()
    return MarketSnapshotResponse(
        as_of=overview.as_of,
        provider=overview.provider,
        stale=overview.stale,
        stale_reason=overview.stale_reason,
        last_success_at=overview.last_success_at,
        items=[_overview_item(item) for item in overview.items],
    )


@market_router.get("/market/breadth", response_model=MarketBreadthResponse)
def get_market_breadth(
    inst_type: InstType = Query(...),
    bar: Bar = Query("1d"),
    as_of: AwareDatetime | None = Query(None),
) -> MarketBreadthResponse:
    """该类别在 `as_of`（缺省为当前时刻）的涨跌家数与同向程度。"""

    overview = market_overview(as_of, bar, inst_type)
    breadth = overview.breadth
    resonance = overview.resonance
    return MarketBreadthResponse(
        inst_type=inst_type,
        bar=overview.bar,
        as_of=overview.as_of,
        breadth=MarketBreadth(
            advancers=breadth.advancers,
            decliners=breadth.decliners,
            unchanged=breadth.unchanged,
            ratio=_ratio_str(breadth.ratio),
            participants=breadth.participants,
        ),
        resonance=MarketResonance(
            strength=_ratio_str(resonance.strength),
            participants=resonance.participants,
            window=resonance.window,
        ),
    )


def _beijing(moment: datetime) -> str:
    return moment.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M")


@market_router.get("/market/events", response_model=MarketEventListResponse)
def get_market_events(
    ticker: str | None = Query(None),
    start: AwareDatetime | None = Query(None),
    end: AwareDatetime | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> MarketEventListResponse:
    """按标的与时间范围读取宏观/公司事件；缺省范围为前后 30/90 天。"""

    now = SystemClock().now()
    events = list_market_events(
        ticker=ticker,
        start=start or now - EVENT_LOOKBACK,
        end=end or now + EVENT_LOOKAHEAD,
        limit=limit,
    )
    return MarketEventListResponse(
        items=[
            MarketEventItem(
                id=item.id,
                event_type=item.event_type,
                title=item.title,
                region=item.region,
                ticker=item.ticker,
                scheduled_at=item.scheduled_at,
                scheduled_at_beijing=_beijing(item.scheduled_at),
                actual=item.actual,
                forecast=item.forecast,
                previous=item.previous,
                importance=item.importance,
                source=item.source,
                source_url=item.source_url,
                received_at=item.received_at,
            )
            for item in events
        ]
    )


@market_router.get("/news", response_model=NewsListResponse)
def get_news(
    ticker: str | None = Query(None),
    industry: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> NewsListResponse:
    """按标的或行业标签读取已采集新闻，保留标题、来源、URL 与发布时间。"""

    items = list_news(ticker=ticker, industry=industry, limit=limit)
    return NewsListResponse(
        items=[
            NewsItemSchema(
                id=item.id,
                title=item.title,
                summary=item.summary,
                publisher=item.publisher,
                url=item.url,
                published_at=item.published_at,
                tickers=list(item.tickers),
                tags=list(item.tags),
                source=item.source,
                received_at=item.received_at,
            )
            for item in items
        ]
    )

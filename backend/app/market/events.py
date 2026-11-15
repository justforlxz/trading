"""宏观/公司事件与新闻：采集写入、按标的与时间读取。

事件与新闻都保留来源、来源 URL 与接收时间。新闻的 ticker 与行业标签以 JSON 文本
保存；查询时按带引号的完整标签匹配，避免 `AA` 命中 `AAPL` 这类子串误判。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from app.core import ValidationError
from app.db import session_scope
from app.market.model import MarketEventRow, NewsItemRow

__all__ = [
    "EventInput",
    "MarketEvent",
    "NewsInput",
    "NewsItem",
    "latest_news",
    "list_market_events",
    "list_news",
    "upsert_market_events",
    "upsert_news",
]

MAX_EVENT_LIMIT = 500
MAX_NEWS_LIMIT = 200


@dataclass(frozen=True, slots=True)
class EventInput:
    """Provider 返回的一条事件；`provider_id` 只用于生成稳定的本地 id。"""

    provider_id: str
    event_type: str
    title: str
    scheduled_at: datetime
    source: str
    received_at: datetime
    region: str | None = None
    ticker: str | None = None
    actual: str | None = None
    forecast: str | None = None
    previous: str | None = None
    importance: str | None = None
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class NewsInput:
    """Provider 返回的一条新闻；`provider_id` 在同一来源内唯一。"""

    provider_id: str
    title: str
    source: str
    received_at: datetime
    summary: str | None = None
    publisher: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    tickers: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MarketEvent:
    id: str
    event_type: str
    title: str
    region: str | None
    ticker: str | None
    scheduled_at: datetime
    actual: str | None
    forecast: str | None
    previous: str | None
    importance: str | None
    source: str
    source_url: str | None
    received_at: datetime


@dataclass(frozen=True, slots=True)
class NewsItem:
    id: str
    provider_id: str
    title: str
    summary: str | None
    publisher: str | None
    url: str | None
    published_at: datetime | None
    tickers: tuple[str, ...]
    tags: tuple[str, ...]
    source: str
    received_at: datetime


def _event(row: MarketEventRow) -> MarketEvent:
    return MarketEvent(
        id=row.id,
        event_type=row.event_type,
        title=row.title,
        region=row.region,
        ticker=row.ticker,
        scheduled_at=row.scheduled_at,
        actual=row.actual,
        forecast=row.forecast,
        previous=row.previous,
        importance=row.importance,
        source=row.source,
        source_url=row.source_url,
        received_at=row.received_at,
    )


def _news(row: NewsItemRow) -> NewsItem:
    return NewsItem(
        id=row.id,
        provider_id=row.provider_id,
        title=row.title,
        summary=row.summary,
        publisher=row.publisher,
        url=row.url,
        published_at=row.published_at,
        tickers=tuple(json.loads(row.tickers_json)),
        tags=tuple(json.loads(row.tags_json)),
        source=row.source,
        received_at=row.received_at,
    )


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _require_text(value: str, name: str) -> str:
    text = value.strip()
    if not text:
        raise ValidationError(f"{name} 不能为空")
    return text


def _require_aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValidationError(f"{name} 必须带时区")
    return value


def _event_id(source: str, provider_id: str) -> str:
    return "evt_" + uuid5(NAMESPACE_URL, f"{source}:{provider_id}").hex[:24]


def _news_id(source: str, provider_id: str) -> str:
    return "news_" + uuid5(NAMESPACE_URL, f"{source}:{provider_id}").hex[:24]


def upsert_market_events(events: Iterable[EventInput]) -> int:
    """按本地 id 幂等写入事件；同一事件重复同步只覆盖字段。"""

    prepared: dict[str, dict[str, object]] = {}
    for item in events:
        source = _require_text(item.source, "source")
        provider_id = _require_text(item.provider_id, "provider_id")
        row_id = _event_id(source, provider_id)
        prepared[row_id] = {
            "id": row_id,
            "event_type": _require_text(item.event_type, "event_type"),
            "title": _require_text(item.title, "title"),
            "region": _clean_optional(item.region),
            "ticker": _clean_optional(item.ticker),
            "scheduled_at": _require_aware(item.scheduled_at, "scheduled_at"),
            "actual": _clean_optional(item.actual),
            "forecast": _clean_optional(item.forecast),
            "previous": _clean_optional(item.previous),
            "importance": _clean_optional(item.importance),
            "source": source,
            "source_url": _clean_optional(item.source_url),
            "received_at": _require_aware(item.received_at, "received_at"),
        }
    if not prepared:
        return 0
    statement = postgresql_insert(MarketEventRow).values(list(prepared.values()))
    statement = statement.on_conflict_do_update(
        index_elements=[MarketEventRow.id],
        set_={
            "event_type": statement.excluded.event_type,
            "title": statement.excluded.title,
            "region": statement.excluded.region,
            "ticker": statement.excluded.ticker,
            "scheduled_at": statement.excluded.scheduled_at,
            "actual": statement.excluded.actual,
            "forecast": statement.excluded.forecast,
            "previous": statement.excluded.previous,
            "importance": statement.excluded.importance,
            "source": statement.excluded.source,
            "source_url": statement.excluded.source_url,
            "received_at": statement.excluded.received_at,
        },
    )
    with session_scope() as session:
        session.execute(statement)
    return len(prepared)


def upsert_news(items: Iterable[NewsInput]) -> int:
    """按 `(source, provider_id)` 幂等写入新闻。"""

    prepared: list[dict[str, object]] = []
    for item in items:
        source = _require_text(item.source, "source")
        provider_id = _require_text(item.provider_id, "provider_id")
        prepared.append(
            {
                "id": _news_id(source, provider_id),
                "provider_id": provider_id,
                "title": _require_text(item.title, "title"),
                "summary": _clean_optional(item.summary),
                "publisher": _clean_optional(item.publisher),
                "url": _clean_optional(item.url),
                "published_at": (
                    None
                    if item.published_at is None
                    else _require_aware(item.published_at, "published_at")
                ),
                "tickers_json": json.dumps(sorted(set(item.tickers)), ensure_ascii=False),
                "tags_json": json.dumps(sorted(set(item.tags)), ensure_ascii=False),
                "source": source,
                "received_at": _require_aware(item.received_at, "received_at"),
            }
        )
    if not prepared:
        return 0
    statement = postgresql_insert(NewsItemRow).values(prepared)
    statement = statement.on_conflict_do_update(
        index_elements=[NewsItemRow.source, NewsItemRow.provider_id],
        set_={
            "title": statement.excluded.title,
            "summary": statement.excluded.summary,
            "publisher": statement.excluded.publisher,
            "url": statement.excluded.url,
            "published_at": statement.excluded.published_at,
            "tickers_json": statement.excluded.tickers_json,
            "tags_json": statement.excluded.tags_json,
            "received_at": statement.excluded.received_at,
        },
    )
    with session_scope() as session:
        session.execute(statement)
    return len(prepared)


def list_market_events(
    *,
    ticker: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
) -> tuple[MarketEvent, ...]:
    """按标的与时间范围读取事件，按事件时间升序。"""

    if not 1 <= limit <= MAX_EVENT_LIMIT:
        raise ValidationError(f"条数上限必须在 1 到 {MAX_EVENT_LIMIT} 之间: {limit}")
    conditions = []
    if ticker is not None:
        conditions.append(MarketEventRow.ticker == _require_text(ticker, "ticker"))
    if start is not None:
        conditions.append(MarketEventRow.scheduled_at >= _require_aware(start, "from"))
    if end is not None:
        conditions.append(MarketEventRow.scheduled_at <= _require_aware(end, "to"))
    statement = select(MarketEventRow)
    if conditions:
        statement = statement.where(*conditions)
    statement = statement.order_by(MarketEventRow.scheduled_at.asc()).limit(limit)
    with session_scope() as session:
        rows = list(session.scalars(statement))
    return tuple(_event(row) for row in rows)


def _label_condition(column: object, label: str) -> object:
    # 完整 JSON 字符串标签：`"AAPL"` 不会命中 `"AAPL-X"`。
    # `autoescape` 把标签里的 `%` 与 `_` 转义成字面量，避免它们退化成 LIKE 通配符。
    return column.contains(f'"{label}"', autoescape=True)  # type: ignore[attr-defined]


def list_news(
    *,
    ticker: str | None = None,
    industry: str | None = None,
    limit: int = 50,
) -> tuple[NewsItem, ...]:
    """按 ticker 或行业标签读取新闻，按发布时间倒序。"""

    if not 1 <= limit <= MAX_NEWS_LIMIT:
        raise ValidationError(f"条数上限必须在 1 到 {MAX_NEWS_LIMIT} 之间: {limit}")
    conditions = []
    if ticker is not None:
        conditions.append(
            _label_condition(NewsItemRow.tickers_json, _require_text(ticker, "ticker"))
        )
    if industry is not None:
        conditions.append(
            _label_condition(NewsItemRow.tags_json, _require_text(industry, "industry"))
        )
    statement = select(NewsItemRow)
    if conditions:
        statement = statement.where(*conditions)
    statement = statement.order_by(
        NewsItemRow.published_at.desc().nullslast(), NewsItemRow.received_at.desc()
    ).limit(limit)
    with session_scope() as session:
        rows = list(session.scalars(statement))
    return tuple(_news(row) for row in rows)


def latest_news(limit: int = 20) -> tuple[NewsItem, ...]:
    """最近新闻；AI 摘要只引用这些已入库内容。"""

    return list_news(limit=limit)

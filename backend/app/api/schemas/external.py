"""外部市场、事件新闻、AI 摘要与系统健康的 HTTP 契约。

外部指标与新闻都保留来源与时间；`stale` / `stale_reason` 表达「这一份数据是否还能
当作当前值」。事件时间同时给出 UTC 与北京时间展示字段，避免前端各自换算。
AI 摘要的每个事实点都必须带至少一条来源；没有来源的句子不进入响应。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import Bar, DecimalString, UtcDatetime

__all__ = [
    "AiSummaryPoint",
    "AiSummaryRequest",
    "AiSummaryResponse",
    "AiSummarySource",
    "ComponentStatus",
    "HealthStatus",
    "MarketEventItem",
    "MarketEventListResponse",
    "MarketOverviewItem",
    "MarketSnapshotResponse",
    "NewsItem",
    "NewsListResponse",
    "QualityStatus",
    "SystemComponent",
    "SystemHealthResponse",
    "SystemSyncRequest",
    "SystemSyncResponse",
]

QualityStatus = Literal["normal", "missing", "delayed", "stale", "abnormal", "pending"]
HealthStatus = Literal["ok", "degraded"]
ComponentStatus = Literal["ok", "stale", "error", "unconfigured"]
SummarySourceType = Literal["news", "alert", "market_overview", "risk"]


class MarketOverviewItem(BaseModel):
    """一个市场指标；缺数据时数值为 `null`，`quality_status` 说明原因。"""

    symbol: str
    name: str
    value: DecimalString | None
    change: DecimalString | None
    change_pct: DecimalString | None
    market_session: str
    source: str
    as_of: UtcDatetime | None
    is_delayed: bool
    quality_status: QualityStatus
    source_url: str | None = None


class MarketSnapshotResponse(BaseModel):
    """五个市场指标的当前快照；顶层 `stale` 表示至少一项不能当作实时值。"""

    as_of: UtcDatetime
    provider: str | None
    stale: bool
    stale_reason: str | None
    last_success_at: UtcDatetime | None
    items: list[MarketOverviewItem]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "as_of": "2026-11-15T06:10:00Z",
                    "provider": "market_data_provider",
                    "stale": False,
                    "stale_reason": None,
                    "last_success_at": "2026-11-15T06:05:00Z",
                    "items": [
                        {
                            "symbol": "NASDAQ",
                            "name": "NASDAQ Composite",
                            "value": "18000.12",
                            "change": "180",
                            "change_pct": "1.01",
                            "market_session": "closed",
                            "source": "market_data_provider",
                            "as_of": "2026-11-15T06:00:00Z",
                            "is_delayed": False,
                            "quality_status": "normal",
                            "source_url": None,
                        }
                    ],
                }
            ]
        }
    )


class MarketEventItem(BaseModel):
    """一条宏观或公司事件；`scheduled_at_beijing` 是展示用北京时间。"""

    id: str
    event_type: str
    title: str
    region: str | None
    ticker: str | None
    scheduled_at: UtcDatetime
    scheduled_at_beijing: str
    actual: str | None
    forecast: str | None
    previous: str | None
    importance: str | None
    source: str
    source_url: str | None
    received_at: UtcDatetime


class MarketEventListResponse(BaseModel):
    """按时间范围与标的条件读取的事件列表。"""

    items: list[MarketEventItem]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "id": "evt_0123456789abcdef01234567",
                            "event_type": "earnings",
                            "title": "AAPL 财报",
                            "region": "US",
                            "ticker": "AAPL",
                            "scheduled_at": "2026-11-16T21:00:00Z",
                            "scheduled_at_beijing": "2026-11-17 05:00",
                            "actual": None,
                            "forecast": "1.20",
                            "previous": "1.10",
                            "importance": "high",
                            "source": "market_data_provider",
                            "source_url": None,
                            "received_at": "2026-11-15T06:10:00Z",
                        }
                    ]
                }
            ]
        }
    )


class NewsItem(BaseModel):
    """一条已采集新闻；标题、来源、URL 与发布时间原样保留。"""

    id: str
    title: str
    summary: str | None
    publisher: str | None
    url: str | None
    published_at: UtcDatetime | None
    tickers: list[str]
    tags: list[str]
    source: str
    received_at: UtcDatetime


class NewsListResponse(BaseModel):
    """按标的或行业标签读取的新闻列表。"""

    items: list[NewsItem]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "id": "news_0123456789abcdef01234567",
                            "title": "AAPL 发布季度业绩",
                            "summary": "收入高于市场预期。",
                            "publisher": "Example News",
                            "url": None,
                            "published_at": "2026-11-15T05:00:00Z",
                            "tickers": ["AAPL"],
                            "tags": ["technology"],
                            "source": "market_data_provider",
                            "received_at": "2026-11-15T06:10:00Z",
                        }
                    ]
                }
            ]
        }
    )


class AiSummarySource(BaseModel):
    """一条可回溯的来源；`id` 对应事件、新闻或提醒的本地标识。"""

    type: SummarySourceType
    id: str
    url: str | None = None


class AiSummaryPoint(BaseModel):
    """摘要里的一个事实点；`sources` 至少一条。"""

    text: str
    sources: list[AiSummarySource] = Field(min_length=1)


class AiSummaryRequest(BaseModel):
    """摘要输入；只读取已采集的数据，不触发外部请求。"""

    include_news: bool = True
    news_limit: int = Field(default=10, ge=1, le=50)

    model_config = ConfigDict(extra="forbid")


class AiSummaryResponse(BaseModel):
    """结构化摘要；没有来源的事实点不会出现在 `points` 或 `risks` 里。"""

    generated_at: UtcDatetime
    overall: str
    points: list[AiSummaryPoint]
    risks: list[AiSummaryPoint]
    disclaimer: str
    stale: bool
    stale_notice: str | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "generated_at": "2026-11-15T06:10:00Z",
                    "overall": "偏强，波动率抬升",
                    "points": [
                        {
                            "text": "NASDAQ Composite 最新 18000.12，较前值 +1.01%。",
                            "sources": [
                                {
                                    "type": "market_overview",
                                    "id": "NASDAQ",
                                    "url": None,
                                }
                            ],
                        }
                    ],
                    "risks": [
                        {
                            "text": "持仓缺少止损：AAPL-USDT-SWAP",
                            "sources": [{"type": "alert", "id": "alert_0123456789abcdef01234567"}],
                        }
                    ],
                    "disclaimer": "仅作信息归纳，不构成交易建议",
                    "stale": False,
                    "stale_notice": None,
                }
            ]
        }
    )


class SystemComponent(BaseModel):
    """一个系统组件的最新状态；错误只给摘要，不带上游原始应答。"""

    name: str
    status: ComponentStatus
    last_success_at: UtcDatetime | None
    error: str | None
    detail: str | None


class SystemHealthResponse(BaseModel):
    """系统健康总览；单项异常不影响其他项，整体状态降为 `degraded`。"""

    status: HealthStatus
    checked_at: UtcDatetime
    components: list[SystemComponent]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "status": "degraded",
                    "checked_at": "2026-11-15T06:10:00Z",
                    "components": [
                        {
                            "name": "database",
                            "status": "ok",
                            "last_success_at": "2026-11-15T06:10:00Z",
                            "error": None,
                            "detail": None,
                        },
                        {
                            "name": "external_provider",
                            "status": "stale",
                            "last_success_at": "2026-11-14T06:00:00Z",
                            "error": "Provider 超时",
                            "detail": "market_data_provider / market_overview",
                        },
                    ],
                }
            ]
        }
    )


class SystemSyncRequest(BaseModel):
    """手动触发一次数据同步；数据集由服务端校验。

    `instruments` 与 `candles` 是 OKX 公共行情的产品入口；其余数据集走外部行情
    Provider。`bar` 与 `days` 只对 `candles` 生效。
    """

    dataset: str = Field(min_length=1, max_length=64)
    provider: str | None = Field(default=None, max_length=64)
    instrument_ids: list[str] = Field(default_factory=list)
    bar: Bar | None = None
    days: int | None = Field(default=None, ge=1, le=3650)

    model_config = ConfigDict(extra="forbid")


class SystemSyncResponse(BaseModel):
    """同步任务结果；任务流水同时写入 `data_sync_jobs`。"""

    job_id: str
    status: str
    rows: int
    error: str | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_id": "job_0123456789abcdef01234567",
                    "status": "succeeded",
                    "rows": 4,
                    "error": None,
                }
            ]
        }
    )

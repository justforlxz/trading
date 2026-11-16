"""市场概况、AI 摘要与系统健康的 HTTP 契约。

市场概况只含 BTC，保留来源、报价时间与 `stale` / `stale_reason` 表达「这一份数据
是否还能当作当前值」。AI 摘要的每个事实点都必须带至少一条来源；没有来源的句子不
进入响应。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import Bar, DecimalString, UtcDatetime

__all__ = [
    "AiSummaryPoint",
    "AiSummaryResponse",
    "AiSummarySource",
    "ComponentStatus",
    "HealthStatus",
    "MarketOverviewItem",
    "MarketSnapshotResponse",
    "QualityStatus",
    "SystemComponent",
    "SystemHealthResponse",
    "SystemSyncRequest",
    "SystemSyncResponse",
]

QualityStatus = Literal["normal", "missing", "delayed", "stale", "abnormal", "pending"]
HealthStatus = Literal["ok", "degraded"]
ComponentStatus = Literal["ok", "stale", "error", "unconfigured"]
SummarySourceType = Literal["alert", "market_overview", "risk"]


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
    """BTC 的当前快照；顶层 `stale` 表示这项数据不能当作实时值。"""

    as_of: UtcDatetime
    stale: bool
    stale_reason: str | None
    items: list[MarketOverviewItem]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "as_of": "2026-11-15T06:10:00Z",
                    "stale": False,
                    "stale_reason": None,
                    "items": [
                        {
                            "symbol": "BTC",
                            "name": "Bitcoin",
                            "value": "65000.5",
                            "change": "1200",
                            "change_pct": "1.88",
                            "market_session": "regular",
                            "source": "okx_spot",
                            "as_of": "2026-11-15T06:09:30Z",
                            "is_delayed": False,
                            "quality_status": "normal",
                            "source_url": None,
                        }
                    ],
                }
            ]
        }
    )


class AiSummarySource(BaseModel):
    """一条可回溯的来源；`id` 对应指标或提醒的本地标识。"""

    type: SummarySourceType
    id: str
    url: str | None = None


class AiSummaryPoint(BaseModel):
    """摘要里的一个事实点；`sources` 至少一条。"""

    text: str
    sources: list[AiSummarySource] = Field(min_length=1)


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
                    "overall": "偏强",
                    "points": [
                        {
                            "text": "Bitcoin 最新 65000.5，较前值 +1.88%。",
                            "sources": [
                                {
                                    "type": "market_overview",
                                    "id": "BTC",
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
                    "status": "ok",
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
                            "name": "okx_rest",
                            "status": "ok",
                            "last_success_at": "2026-11-15T06:05:00Z",
                            "error": None,
                            "detail": "candles 最近一次同步成功且仍在时效内",
                        },
                    ],
                }
            ]
        }
    )


class SystemSyncRequest(BaseModel):
    """手动触发一次 OKX 行情同步；`bar` 与 `days` 只对 `candles` 生效。"""

    dataset: str = Field(min_length=1, max_length=64)
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

"""宏观数据的 HTTP 契约：首页「市场概况」与关注列表「市场风险」共用一个总览。

`MacroReading` 按「序列 + 粒度」一行：同一序列的分钟级与日线结算值各自带 `as_of` 与
`is_delayed`，前端不把两个时间合成一个。`MacroSpread` 只由同一结算日的 2Y 与 10Y
日线结算值算出，不可用时给 `reason`，不给一个用分钟级顶替的近似值。

所有响应都带 `examples`：契约由 `contracts/openapi.json` 生成前端类型与 MSW fixture，
没有 example 就生成不出可用的桩数据。
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import DecimalString, UtcDatetime

__all__ = [
    "MacroGranularity",
    "MacroOverviewResponse",
    "MacroQualityStatus",
    "MacroReading",
    "MacroSource",
    "MacroSpread",
    "MacroSyncResponse",
    "MacroSyncResultItem",
    "MacroSyncStatus",
    "VixRegime",
]

MacroGranularity = Literal["minute", "daily"]
MacroQualityStatus = Literal["normal", "stale", "missing"]
MacroSyncStatus = Literal["synced", "unchanged", "skipped", "failed"]
VixRegime = Literal["low", "normal", "elevated", "panic"]


class MacroReading(BaseModel):
    """一个序列在一个粒度上的读数；缺数据时 `value` 为空并给出 `error`。"""

    series_id: str
    name: str
    unit: str
    granularity: MacroGranularity
    provider: str
    source_url: str | None = None
    value: DecimalString | None = None
    change: DecimalString | None = None
    as_of: UtcDatetime | None = None
    is_delayed: bool = False
    market_session: str | None = None
    quality_status: MacroQualityStatus
    regime: VixRegime | None = None
    error: str | None = None


class MacroSource(BaseModel):
    """一个来源：provider 名与它的上游地址。"""

    provider: str
    source_url: str | None = None


class MacroSpread(BaseModel):
    """2Y→10Y 利差；`available=false` 时 `reason` 说明为什么算不出来。

    `sources` 是配对实际用到的日线来源：默认配置下 2Y 与 10Y 都来自财政部，合成一条；
    两个序列配成不同 provider 时给出两条，不把两个来源写成一个。
    """

    available: bool
    value_bp: DecimalString | None = None
    inverted: bool = False
    trading_day: date | None = None
    quality_status: MacroQualityStatus
    reason: str | None = None
    sources: list[MacroSource]


class MacroOverviewResponse(BaseModel):
    """首页与关注列表要的宏观读数；`stale` 表示上游失败、数值来自上次落库。"""

    as_of: UtcDatetime
    stale: bool
    stale_reason: str | None
    readings: list[MacroReading]
    spread: MacroSpread

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "as_of": "2026-11-22T07:01:00Z",
                    "stale": False,
                    "stale_reason": None,
                    "readings": [
                        {
                            "series_id": "us10y",
                            "name": "美国 10 年期国债",
                            "unit": "%",
                            "granularity": "minute",
                            "provider": "yahoo",
                            "source_url": None,
                            "value": "4.92",
                            "change": "-0.13",
                            "as_of": "2026-11-20T20:59:00Z",
                            "is_delayed": True,
                            "market_session": "open",
                            "quality_status": "normal",
                            "regime": None,
                            "error": None,
                        },
                        {
                            "series_id": "us10y",
                            "name": "美国 10 年期国债",
                            "unit": "%",
                            "granularity": "daily",
                            "provider": "treasury",
                            "source_url": None,
                            "value": "4.92",
                            "change": "-0.12",
                            "as_of": "2026-11-20T21:00:00Z",
                            "is_delayed": False,
                            "market_session": "closed",
                            "quality_status": "normal",
                            "regime": None,
                            "error": None,
                        },
                        {
                            "series_id": "us2y",
                            "name": "美国 2 年期国债",
                            "unit": "%",
                            "granularity": "daily",
                            "provider": "treasury",
                            "source_url": None,
                            "value": "4.63",
                            "change": "-0.13",
                            "as_of": "2026-11-20T21:00:00Z",
                            "is_delayed": False,
                            "market_session": "closed",
                            "quality_status": "normal",
                            "regime": None,
                            "error": None,
                        },
                        {
                            "series_id": "vix",
                            "name": "恐慌指数 VIX",
                            "unit": "点",
                            "granularity": "minute",
                            "provider": "yahoo",
                            "source_url": None,
                            "value": "35.89",
                            "change": "7.45",
                            "as_of": "2026-11-20T20:59:00Z",
                            "is_delayed": True,
                            "market_session": "open",
                            "quality_status": "normal",
                            "regime": "panic",
                            "error": None,
                        },
                        {
                            "series_id": "vix",
                            "name": "恐慌指数 VIX",
                            "unit": "点",
                            "granularity": "daily",
                            "provider": "cboe",
                            "source_url": None,
                            "value": "35.89",
                            "change": "7.45",
                            "as_of": "2026-11-20T21:00:00Z",
                            "is_delayed": False,
                            "market_session": "closed",
                            "quality_status": "normal",
                            "regime": "panic",
                            "error": None,
                        },
                    ],
                    "spread": {
                        "available": True,
                        "value_bp": "29",
                        "inverted": False,
                        "trading_day": "2026-11-20",
                        "quality_status": "normal",
                        "reason": None,
                        "sources": [{"provider": "treasury", "source_url": None}],
                    },
                }
            ]
        }
    )


class MacroSyncResultItem(BaseModel):
    """一个抓取单元的手动刷新结果；`skipped` 表示同一单元正在跑。"""

    series_id: str
    granularity: MacroGranularity
    provider: str
    status: MacroSyncStatus
    rows: int = Field(ge=0)
    error: str | None = None


class MacroSyncResponse(BaseModel):
    """一次手动刷新的结果，按单元逐条返回。"""

    as_of: UtcDatetime
    results: list[MacroSyncResultItem]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "as_of": "2026-11-22T07:01:00Z",
                    "results": [
                        {
                            "series_id": "us10y",
                            "granularity": "minute",
                            "provider": "yahoo",
                            "status": "synced",
                            "rows": 400,
                            "error": None,
                        },
                        {
                            "series_id": "vix",
                            "granularity": "minute",
                            "provider": "yahoo",
                            "status": "skipped",
                            "rows": 0,
                            "error": None,
                        },
                    ],
                }
            ]
        }
    )

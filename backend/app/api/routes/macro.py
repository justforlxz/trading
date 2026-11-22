"""宏观数据端点：总览只读库，手动刷新按单元加锁。

`GET /api/macro/overview` 只读 `macro_observations`，任何时候都不发起上游请求：上游
不可用时返回上次落库的值并标 `stale`，HTTP 仍然是 200。抓取的定时来源只有
`app/jobs/market_data.py` 的调度器；这里的 `POST /api/macro/sync` 是用户明确要求刷新
时才走的手动入口，与调度器共用同一套单元锁与退避状态。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter

from app.api.mapping import decimal_str
from app.api.schemas import (
    MacroOverviewResponse,
    MacroReading,
    MacroSource,
    MacroSpread,
    MacroSyncResponse,
    MacroSyncResultItem,
)
from app.core import SystemClock
from app.macro import (
    MacroOverview,
    SeriesReading,
    SpreadReading,
)
from app.macro import (
    MacroSource as MacroSourceValue,
)
from app.macro import (
    macro_overview as _overview,
)
from app.macro import (
    sync as _sync,
)

__all__ = ["macro_router"]

macro_router = APIRouter(tags=["macro"])


def _macro_overview() -> MacroOverview:
    """当前宏观读数；测试通过替换本函数注入固定数据。"""

    return _overview()


def _value(value: Decimal | None) -> str | None:
    return None if value is None else decimal_str(value)


def _reading(item: SeriesReading) -> MacroReading:
    return MacroReading(
        series_id=item.series_id,
        name=item.name,
        unit=item.unit,
        granularity=item.granularity,
        provider=item.provider,
        source_url=item.source_url,
        value=_value(item.value),
        change=_value(item.change),
        as_of=item.as_of,
        is_delayed=item.is_delayed,
        market_session=item.market_session,
        quality_status=item.quality_status,
        regime=item.regime,
        error=item.error,
    )


def _source(item: MacroSourceValue) -> MacroSource:
    return MacroSource(provider=item.provider, source_url=item.source_url)


def _spread(item: SpreadReading) -> MacroSpread:
    return MacroSpread(
        available=item.available,
        value_bp=_value(item.value_bp),
        inverted=item.inverted,
        trading_day=item.trading_day,
        quality_status=item.quality_status,
        reason=item.reason,
        sources=[_source(source) for source in item.sources],
    )


@macro_router.get("/macro/overview", response_model=MacroOverviewResponse)
def get_macro_overview() -> MacroOverviewResponse:
    """首页与关注列表的宏观读数；只读库，不触发上游请求。"""

    snapshot = _macro_overview()
    return MacroOverviewResponse(
        as_of=snapshot.as_of,
        stale=snapshot.stale,
        stale_reason=snapshot.stale_reason,
        readings=[_reading(item) for item in snapshot.readings],
        spread=_spread(snapshot.spread),
    )


@macro_router.post("/macro/sync", response_model=MacroSyncResponse)
def post_macro_sync() -> MacroSyncResponse:
    """手动刷新：同一单元正在运行或处于退避时返回 `skipped`，不排队。"""

    now: datetime = SystemClock().now()
    results = _sync(coalesce=True)
    return MacroSyncResponse(
        as_of=now,
        results=[
            MacroSyncResultItem(
                series_id=item.series_id,
                granularity=item.granularity,
                provider=item.provider,
                status=item.status,
                rows=item.rows,
                error=item.error,
            )
            for item in results
        ],
    )

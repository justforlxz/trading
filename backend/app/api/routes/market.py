"""市场端点：BTC 市场概况与类别广度。

`/market/overview` 只返回 BTC 的最新价、24 小时涨跌、市场时段与报价时间，数据来自
OKX 公共 ticker；取不到时数值为 `null`、`quality_status=missing`，顶层 `stale` 为真。
`/market/breadth` 保留按 `SPOT` / `SWAP` 统计的涨跌家数与共振，两类标的的交易时段
不同，广度不能混成同一个横截面。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from app.api.mapping import decimal_str
from app.api.schemas import (
    MarketBreadth,
    MarketBreadthResponse,
    MarketOverviewItem,
    MarketResonance,
    MarketSnapshotResponse,
)
from app.api.schemas.common import Bar, InstType
from app.market import MarketOverviewItem as OverviewItem
from app.market import (
    MarketOverviewSnapshot,
    market_overview,
    market_overview_snapshot,
)

__all__ = ["market_router"]

market_router = APIRouter(tags=["market"])

# 契约的 DecimalString 只保证 12 位小数；8/3 这类比值是无限小数，出接口前必须量化。
_VALUE_QUANTUM = Decimal("1e-12")


def _ratio_str(value: float | None) -> str | None:
    """比值 → 契约里的定点字符串；没有数时如实给 `null`，不补 0。"""

    if value is None:
        return None
    return decimal_str(Decimal(str(value)).quantize(_VALUE_QUANTUM, rounding=ROUND_HALF_UP))


def _market_overview() -> MarketOverviewSnapshot:
    """BTC 的当前快照；测试通过替换本函数注入固定报价。"""

    return market_overview_snapshot()


def _overview_item(item: OverviewItem) -> MarketOverviewItem:
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
    """BTC 的最新值、24 小时涨跌、时段、来源与报价时间。"""

    overview = _market_overview()
    return MarketSnapshotResponse(
        as_of=overview.as_of,
        stale=overview.stale,
        stale_reason=overview.stale_reason,
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

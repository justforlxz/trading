"""市场总览端点：某一类别（`SPOT` / `SWAP`）在某一时点的横截面广度与共振。

`inst_type` 必填、没有默认值：两类标的的交易时段不同，把它们混成同一个横截面统计
出来的涨跌家数没有意义。参与标的、来源选择与取数区间都在 `app.market.market_overview`
里完成，这一层只做入参校验与响应组装。

契约里的 Decimal 以字符串返回（`DecimalString`），比值是无限小数，必须先按契约的
12 位小数精度量化，否则响应模型校验直接报 500。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from app.api.mapping import decimal_str
from app.api.schemas import MarketBreadth, MarketOverviewResponse, MarketResonance
from app.api.schemas.common import Bar, InstType
from app.market import market_overview

__all__ = ["market_router"]

market_router = APIRouter(tags=["market"])

# 契约的 DecimalString 只保证 12 位小数；8/3 这类比值是无限小数，出接口前必须量化。
_VALUE_QUANTUM = Decimal("1e-12")


def _ratio_str(value: float | None) -> str | None:
    """比值 → 契约里的定点字符串；没有数时如实给 `null`，不补 0。"""

    if value is None:
        return None
    return decimal_str(Decimal(str(value)).quantize(_VALUE_QUANTUM, rounding=ROUND_HALF_UP))


@market_router.get("/market/overview", response_model=MarketOverviewResponse)
def get_market_overview(
    inst_type: InstType = Query(...),
    bar: Bar = Query("1d"),
    as_of: AwareDatetime | None = Query(None),
) -> MarketOverviewResponse:
    """该类别在 `as_of`（缺省为当前时刻）的涨跌家数与同向程度。"""

    overview = market_overview(as_of, bar, inst_type)
    breadth = overview.breadth
    resonance = overview.resonance
    return MarketOverviewResponse(
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

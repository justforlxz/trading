"""概览契约：市场驾驶舱五个区块的只读聚合。

五个区块的数据全部来自既有节点的读模型：市场时段与来源取 `app.market.session`
的纯函数，广度与共振取 T2.5 的市场总览，组合取 T7.1 的敞口总览，机会取 T3.4
的已落库记录，风险告警取 T6.1 的 `risk_events`。本契约不定义新的业务数值。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import DataSource, DecimalString, InstType, UtcDatetime
from app.api.schemas.correlation import MarketOverviewResponse
from app.api.schemas.opportunity import Opportunity
from app.api.schemas.risk import RiskEvent

__all__ = [
    "MarketState",
    "OverviewResponse",
    "PortfolioStrategyBrief",
    "PortfolioSummary",
]

MarketSession = Literal["pre", "regular", "post", "closed"]


class MarketState(BaseModel):
    """一个类别在 `as_of` 时刻的资产时段与参考行情来源。

    类别只是展示分组：`SPOT` / `SWAP` 内部可能同时含有多种资产，类别层级没有
    唯一的 `asset_type`，因此这里与 T1.7 一致地使用类别规则作为兜底取值。
    """

    inst_type: InstType
    session: MarketSession
    primary_source: DataSource


class PortfolioStrategyBrief(BaseModel):
    """单个策略实例的当前持仓数。"""

    instance_id: str
    name: str
    open_positions: int


class PortfolioSummary(BaseModel):
    """全局组合概览；各策略明细来自 T7.1 的策略组合列表。"""

    gross_exposure: DecimalString
    net_exposure: DecimalString
    open_positions: int
    strategies: list[PortfolioStrategyBrief]


_EXAMPLE_OPPORTUNITY = {
    "opportunity_id": "opp_0001",
    "mode": "target",
    "anchor_product_key": "AAPL",
    "as_of": "2026-11-10T00:00:00Z",
    "score": "0.78",
    "legs": [
        {
            "inst_id": "MSFT-USDT-SWAP",
            "inst_type": "SWAP",
            "product_key": "MSFT",
            "direction": "long",
            "score": "0.82",
        }
    ],
    "evidence": '{"correlation":0.87,"breadth":0.8,"resonance":0.62}',
    "status": "new",
}

_EXAMPLE_RISK_EVENT = {
    "event_id": "re_0001",
    "instance_id": "si_0001",
    "inst_id": "AAPL-USDT-SWAP",
    "rule": "max_leverage",
    "detail": "杠杆 25 超过上限 20",
    "created_at": "2026-11-10T07:00:00Z",
    "resolved_at": None,
}

_EXAMPLE_OVERVIEW = {
    "as_of": "2026-11-10T08:00:00Z",
    "market_states": [
        {"inst_type": "SPOT", "session": "regular", "primary_source": "okx_spot"},
        {"inst_type": "SWAP", "session": "post", "primary_source": "us_equity_proxy"},
    ],
    "market": [
        {
            "inst_type": "SPOT",
            "bar": "1d",
            "as_of": "2026-11-10T08:00:00Z",
            "breadth": {
                "advancers": 8,
                "decliners": 2,
                "unchanged": 1,
                "ratio": "4",
                "participants": 11,
            },
            "resonance": {"strength": "0.62", "participants": 11, "window": 20},
        },
        {
            "inst_type": "SWAP",
            "bar": "1d",
            "as_of": "2026-11-10T08:00:00Z",
            "breadth": {
                "advancers": 5,
                "decliners": 5,
                "unchanged": 0,
                "ratio": "1",
                "participants": 10,
            },
            "resonance": {"strength": "0", "participants": 10, "window": 20},
        },
    ],
    "portfolio": {
        "gross_exposure": "3510.40",
        "net_exposure": "1997.15",
        "open_positions": 3,
        "strategies": [
            {
                "instance_id": "si_0001",
                "name": "AAPL 均线趋势",
                "open_positions": 1,
            }
        ],
    },
    "recent_opportunities": [_EXAMPLE_OPPORTUNITY],
    "risk_events": [_EXAMPLE_RISK_EVENT],
}


class OverviewResponse(BaseModel):
    """首页市场驾驶舱：市场状态、共振、组合、机会流与风险告警。"""

    as_of: UtcDatetime
    market_states: list[MarketState]
    market: list[MarketOverviewResponse]
    portfolio: PortfolioSummary
    recent_opportunities: list[Opportunity]
    risk_events: list[RiskEvent]

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_OVERVIEW]})

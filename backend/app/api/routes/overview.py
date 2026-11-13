"""首页市场驾驶舱：五个区块的只读聚合。

这里只做读取与响应组装，不写任何表，也不重新计算指标：

- 市场状态：`app.market.session` 的 `asset_session` / `primary_source`，按类别各取一次。
  类别内部可能同时含有加密资产与代币化股票，类别层级没有唯一的 `asset_type`，
  因此与 T1.7 的口径一致，用类别规则作为兜底输入。
- 共振强度：`app.market.market_overview`，两类标的各自统计。
- 组合概览：`app.portfolio.exposure_overview` 与 `list_portfolios`。
- 机会流：`app.opportunity.list_opportunities`，已按 `as_of` 倒序。
- 风险告警：`app.risk.list_risk_events`，未处置优先。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from app.api.mapping import decimal_str
from app.api.schemas import (
    MarketBreadth,
    MarketOverviewResponse,
    MarketResonance,
    MarketState,
    Opportunity,
    OpportunityLeg,
    OverviewResponse,
    PortfolioStrategyBrief,
    PortfolioSummary,
    RiskEvent,
)
from app.market import asset_session, market_overview, primary_source
from app.opportunity import list_opportunities
from app.portfolio import exposure_overview, list_portfolios
from app.risk import list_risk_events

__all__ = ["overview_router"]

overview_router = APIRouter(tags=["overview"])

# 两类标的的交易时段不同，驾驶舱按类别各显示一次，不跨类别合并。
INST_TYPES = ("SPOT", "SWAP")
# 驾驶舱只展示最近几条，完整列表由各自域端点提供。
FLOW_LIMIT = 6
WARNING_LIMIT = 6
# T6.1 的读服务只按时间倒序分页，没有处置状态过滤。首页要在整个可读窗口里挑出
# 未处置事件，因此按该服务的读取上限取一遍再排序；上限由 `list_risk_events` 自己校验。
WARNING_SCAN_LIMIT = 500

_VALUE_QUANTUM = Decimal("1e-12")


def _ratio_str(value: float | None) -> str | None:
    """比值 → 契约里的定点字符串；没有数时如实给 `null`，不补 0。"""

    if value is None:
        return None
    return decimal_str(Decimal(str(value)).quantize(_VALUE_QUANTUM, rounding=ROUND_HALF_UP))


def _market_states(moment: datetime) -> list[MarketState]:
    """每个类别一行；`asset_type` 留空以使用类别规则兜底。"""

    return [
        MarketState(
            inst_type=inst_type,
            session=session,
            primary_source=primary_source(session, "", inst_type),
        )
        for inst_type in INST_TYPES
        for session in [asset_session("", moment, inst_type=inst_type)]
    ]


def _market_snapshots(moment: datetime) -> list[MarketOverviewResponse]:
    snapshots: list[MarketOverviewResponse] = []
    for inst_type in INST_TYPES:
        overview = market_overview(moment, "1d", inst_type)
        snapshots.append(
            MarketOverviewResponse(
                inst_type=overview.inst_type,
                bar=overview.bar,
                as_of=overview.as_of,
                breadth=MarketBreadth(
                    advancers=overview.breadth.advancers,
                    decliners=overview.breadth.decliners,
                    unchanged=overview.breadth.unchanged,
                    ratio=_ratio_str(overview.breadth.ratio),
                    participants=overview.breadth.participants,
                ),
                resonance=MarketResonance(
                    strength=_ratio_str(overview.resonance.strength),
                    participants=overview.resonance.participants,
                    window=overview.resonance.window,
                ),
            )
        )
    return snapshots


def _portfolio_summary() -> PortfolioSummary:
    portfolios, _ = list_portfolios()
    budget = sum((item.capital_budget for item in portfolios), Decimal(0))
    if budget > 0:
        exposure = exposure_overview()
        gross_exposure = exposure.gross_exposure
        net_exposure = exposure.net_exposure
        open_positions = exposure.open_positions
    else:
        # T7.1 的敞口聚合要求组合权益大于 0；没有分配预算时每条腿的权重都是 0，
        # 直接给出 0，仍然保留各策略真实的持仓数。
        gross_exposure = net_exposure = Decimal(0)
        open_positions = sum((item.open_positions for item in portfolios), 0)
    return PortfolioSummary(
        gross_exposure=decimal_str(gross_exposure),
        net_exposure=decimal_str(net_exposure),
        open_positions=open_positions,
        strategies=[
            PortfolioStrategyBrief(
                instance_id=item.instance_id,
                name=item.name,
                open_positions=item.open_positions,
            )
            for item in portfolios
        ],
    )


def _opportunities() -> list[Opportunity]:
    records, _ = list_opportunities(limit=FLOW_LIMIT)
    return [
        Opportunity(
            opportunity_id=record.opportunity_id,
            mode=record.mode,
            anchor_product_key=record.anchor_product_key,
            as_of=record.as_of,
            score=decimal_str(record.score),
            legs=[
                OpportunityLeg(
                    inst_id=leg.inst_id,
                    inst_type=leg.inst_type,
                    product_key=leg.product_key,
                    direction=leg.direction,
                    score=decimal_str(leg.score),
                )
                for leg in record.legs
            ],
            evidence=record.evidence,
            status=record.status,
        )
        for record in records
    ]


def _risk_events() -> list[RiskEvent]:
    # 只取最近几条再排序会让较早的未处置事件被大量已处置记录挤出窗口，首页因此
    # 看不到真正待处理的告警。这里按 T6.1 读服务允许的上限取一遍，再按「未处置优先、
    # 同组内时间倒序」排出首页展示的几条。
    records, _ = list_risk_events(limit=WARNING_SCAN_LIMIT)
    ordered = sorted(
        records,
        key=lambda record: (
            record.resolved_at is not None,
            -record.created_at.timestamp(),
            record.event_id,
        ),
    )[:WARNING_LIMIT]
    return [
        RiskEvent(
            event_id=record.event_id,
            instance_id=record.instance_id,
            inst_id=record.inst_id,
            rule=record.rule,
            detail=record.detail,
            created_at=record.created_at,
            resolved_at=record.resolved_at,
        )
        for record in ordered
    ]


@overview_router.get("/overview", response_model=OverviewResponse)
def get_overview(as_of: AwareDatetime | None = Query(None)) -> OverviewResponse:
    """市场驾驶舱聚合；同一 `as_of` 与同一份库状态返回相同 JSON。"""

    moment = datetime.now(tz=UTC) if as_of is None else as_of
    moment = moment.replace(microsecond=0)
    return OverviewResponse(
        as_of=moment,
        market_states=_market_states(moment),
        market=_market_snapshots(moment),
        portfolio=_portfolio_summary(),
        recent_opportunities=_opportunities(),
        risk_events=_risk_events(),
    )

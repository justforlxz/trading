"""带来源的 AI 摘要端点。

摘要只读取 BTC 市场快照与待处理提醒；不调用外部模型、不产生订单、不修改提醒、
不决定风险等级。每个事实点都带来源，没有来源的句子不输出。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.alerts import list_alerts
from app.api.schemas import (
    AiSummaryPoint,
    AiSummaryResponse,
    AiSummarySource,
)
from app.core import SystemClock
from app.dashboard import build_ai_summary
from app.market import market_overview_snapshot

__all__ = ["ai_router"]

ai_router = APIRouter(tags=["ai"])


@ai_router.post("/ai/summary", response_model=AiSummaryResponse)
def post_ai_summary() -> AiSummaryResponse:
    """把 BTC 市场快照与待处理提醒归纳成带来源的结构化摘要。"""

    overview = market_overview_snapshot()
    alerts, _ = list_alerts(status="pending", limit=20)
    summary = build_ai_summary(
        generated_at=SystemClock().now(),
        overview=overview,
        alerts=alerts,
    )
    return AiSummaryResponse(
        generated_at=summary.generated_at,
        overall=summary.overall,
        points=[
            AiSummaryPoint(
                text=point.text,
                sources=[
                    AiSummarySource(type=source.type, id=source.id, url=source.url)
                    for source in point.sources
                ],
            )
            for point in summary.points
        ],
        risks=[
            AiSummaryPoint(
                text=point.text,
                sources=[
                    AiSummarySource(type=source.type, id=source.id, url=source.url)
                    for source in point.sources
                ],
            )
            for point in summary.risks
        ],
        disclaimer=summary.disclaimer,
        stale=summary.stale,
        stale_notice=summary.stale_notice,
    )

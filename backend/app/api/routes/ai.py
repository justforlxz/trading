"""带来源的 AI 摘要端点。

摘要只读取已采集的市场快照、新闻与提醒；不调用外部模型、不产生订单、不修改提醒、
不决定风险等级。每个事实点都带来源，没有来源的句子不输出。
"""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter

from app.alerts import list_alerts
from app.api.providers import select_provider
from app.api.schemas import (
    AiSummaryPoint,
    AiSummaryRequest,
    AiSummaryResponse,
    AiSummarySource,
)
from app.core import SystemClock
from app.dashboard import build_ai_summary
from app.market import (
    MarketOverviewService,
    latest_news,
)

__all__ = ["ai_router"]

ai_router = APIRouter(tags=["ai"])


@ai_router.post("/ai/summary", response_model=AiSummaryResponse)
def post_ai_summary(payload: AiSummaryRequest) -> AiSummaryResponse:
    """把市场快照、新闻与待处理提醒归纳成带来源的结构化摘要。"""

    selection = select_provider()
    overview = MarketOverviewService(provider=selection.provider).overview()
    if selection.error is not None:
        overview = replace(
            overview,
            provider=selection.name,
            stale=True,
            stale_reason=selection.error,
        )
    news = latest_news(limit=payload.news_limit) if payload.include_news else ()
    alerts, _ = list_alerts(status="pending", limit=20)
    summary = build_ai_summary(
        generated_at=SystemClock().now(),
        overview=overview,
        news=news,
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

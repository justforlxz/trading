"""带来源的市场摘要：只归纳已采集的市场快照、新闻与提醒。

这里不调用任何外部模型或交易所接口，也不产生订单、修改提醒或决定风险等级。规则
固定，同样的输入必然得到同样的输出：

- 市场指标与新闻各生成一个事实点，来源分别指向指标标识与新闻 URL；
- 待处理的高严重度提醒生成风险点，来源指向提醒标识；
- 没有任何来源的句子不输出；新闻没有 URL 时不进入「能点回来源」的事实点；
- 市场数据陈旧时，`stale` 为真，`stale_notice` 写明原因，整体结论也带「数据不完整」。

后续接入外部模型时，只需替换文字生成部分，来源校验与输出结构不变。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.alerts import AlertRecord
from app.market import ExternalMarketOverview as MarketOverview
from app.market import NewsItem

__all__ = [
    "DISCLAIMER",
    "AiSummary",
    "SummaryPoint",
    "SummarySource",
    "build_ai_summary",
]

DISCLAIMER = "仅作信息归纳，不构成交易建议"
RISK_SEVERITIES = frozenset({"critical", "high"})
_INDEX_SYMBOLS = frozenset({"NASDAQ", "SP500", "DOW"})


@dataclass(frozen=True, slots=True)
class SummarySource:
    type: str
    id: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class SummaryPoint:
    text: str
    sources: tuple[SummarySource, ...]


@dataclass(frozen=True, slots=True)
class AiSummary:
    generated_at: datetime
    overall: str
    points: tuple[SummaryPoint, ...]
    risks: tuple[SummaryPoint, ...]
    disclaimer: str
    stale: bool
    stale_notice: str | None


def _number(value: Decimal) -> str:
    """指标数值 → 易读的定点文本；去掉没有意义的尾随零。"""

    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _change(value: Decimal | None) -> str:
    if value is None:
        return ""
    sign = "+" if value > 0 else ""
    return f"，较前值 {sign}{_number(value)}%"


def _market_points(overview: MarketOverview) -> tuple[SummaryPoint, ...]:
    points: list[SummaryPoint] = []
    for item in overview.items:
        if item.value is None:
            continue
        text = f"{item.name} 最新 {_number(item.value)}{_change(item.change_pct)}。"
        points.append(
            SummaryPoint(
                text=text,
                sources=(
                    SummarySource(
                        type="market_overview",
                        id=item.symbol,
                        url=item.source_url,
                    ),
                ),
            )
        )
    return tuple(points)


def _news_points(news: Sequence[NewsItem]) -> tuple[SummaryPoint, ...]:
    points: list[SummaryPoint] = []
    for item in news:
        if item.url is None or not item.title.strip():
            continue
        points.append(
            SummaryPoint(
                text=item.title.strip(),
                sources=(SummarySource(type="news", id=item.id, url=item.url),),
            )
        )
    return tuple(points)


def _risk_points(alerts: Sequence[AlertRecord]) -> tuple[SummaryPoint, ...]:
    points: list[SummaryPoint] = []
    for alert in alerts:
        if alert.severity not in RISK_SEVERITIES:
            continue
        text = f"{alert.title}：{alert.detail}" if alert.detail else alert.title
        points.append(
            SummaryPoint(
                text=text,
                sources=(SummarySource(type="alert", id=alert.id),),
            )
        )
    return tuple(points)


def _overall(overview: MarketOverview) -> str:
    changes = [
        item.change_pct
        for item in overview.items
        if item.symbol in _INDEX_SYMBOLS and item.value is not None and item.change_pct is not None
    ]
    if not changes:
        return "数据不足，暂不归纳"
    positive = sum(1 for value in changes if value > 0)
    negative = sum(1 for value in changes if value < 0)
    if positive == len(changes):
        state = "偏强"
    elif negative == len(changes):
        state = "偏弱"
    elif positive > negative:
        state = "偏强"
    elif negative > positive:
        state = "偏弱"
    else:
        state = "分化"
    vix = next((item for item in overview.items if item.symbol == "VIX"), None)
    if vix is not None and vix.value is not None and vix.change_pct is not None:
        if vix.change_pct > 0:
            state += "，波动率抬升"
        elif vix.change_pct < 0:
            state += "，波动率回落"
    if overview.stale:
        return f"数据不完整；{state}"
    return state


def build_ai_summary(
    *,
    generated_at: datetime,
    overview: MarketOverview,
    news: Sequence[NewsItem] = (),
    alerts: Sequence[AlertRecord] = (),
) -> AiSummary:
    """把已采集数据归纳成固定结构；事实点全部带来源。"""

    points = _market_points(overview) + _news_points(news)
    risks = _risk_points(alerts)
    return AiSummary(
        generated_at=generated_at,
        overall=_overall(overview),
        points=points,
        risks=risks,
        disclaimer=DISCLAIMER,
        stale=overview.stale,
        stale_notice=overview.stale_reason if overview.stale else None,
    )

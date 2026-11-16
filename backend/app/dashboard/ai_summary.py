"""带来源的市场摘要：只归纳 BTC 市场快照与待处理提醒。

这里不调用任何外部模型或交易所接口，也不产生订单、修改提醒或决定风险等级。规则
固定，同样的输入必然得到同样的输出：

- BTC 快照生成一个事实点，来源指向指标标识；
- 待处理的高严重度提醒生成风险点，来源指向提醒标识；
- 没有任何来源的句子不输出；
- 市场数据陈旧时，`stale` 为真，`stale_notice` 写明原因，整体结论也带「数据不完整」。

后续接入外部模型时，只需替换文字生成部分，来源校验与输出结构不变。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.alerts import AlertRecord
from app.market import MarketOverviewSnapshot as MarketOverview

__all__ = [
    "DISCLAIMER",
    "AiSummary",
    "SummaryPoint",
    "SummarySource",
    "build_ai_summary",
]

DISCLAIMER = "仅作信息归纳，不构成交易建议"
RISK_SEVERITIES = frozenset({"critical", "high"})


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
    btc = next((item for item in overview.items if item.symbol == "BTC"), None)
    if btc is None or btc.value is None or btc.change_pct is None:
        return "数据不足，暂不归纳"
    if btc.change_pct > 0:
        state = "偏强"
    elif btc.change_pct < 0:
        state = "偏弱"
    else:
        state = "分化"
    if overview.stale:
        return f"数据不完整；{state}"
    return state


def build_ai_summary(
    *,
    generated_at: datetime,
    overview: MarketOverview,
    alerts: Sequence[AlertRecord] = (),
) -> AiSummary:
    """把已采集数据归纳成固定结构；事实点全部带来源。"""

    points = _market_points(overview)
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

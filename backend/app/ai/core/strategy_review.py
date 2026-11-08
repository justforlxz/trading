"""策略与回测的解读文本: 引用逐项对应 GET 接口返回的真实字段。

回测指标只搬运 `load_metrics` 的 Decimal 字符串, 不做任何重算; 亏损结论只描述
事实, 不出现加仓/扩大仓位一类建议。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.ai.core.citations import citation

GROWTH_ADVICE_TERMS = (
    "加仓",
    "扩大仓位",
    "加大仓位",
    "增加仓位",
    "提高仓位",
    "重仓",
    "increase position",
    "add position",
    "scale up position",
)


def strategy_citations(
    *,
    strategy: Mapping[str, Any],
    legs: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    source = f"GET /api/v1/strategies/{strategy.get('id')}"
    items: list[dict[str, Any]] = [
        citation(
            "strategy",
            source,
            strategy_id=strategy.get("id"),
            version=strategy.get("version"),
            status=strategy.get("status"),
            kind=strategy.get("kind"),
        )
    ]
    for leg in legs:
        items.append(
            citation(
                "strategy_leg",
                source,
                strategy_id=strategy.get("id"),
                instrument_id=leg.get("instrument_id"),
                inst_id=leg.get("inst_id"),
                side=leg.get("side"),
                target_weight=leg.get("target_weight"),
                rationale=leg.get("rationale"),
                rank=leg.get("rank"),
            )
        )
    return items


def strategy_summary(
    *,
    strategy: Mapping[str, Any],
    legs: list[Mapping[str, Any]],
    approval_count: int,
) -> str:
    if not legs:
        return f"数据不足: 策略 {strategy.get('id')} 没有可用腿。缺失项: strategy_legs"
    parts = [
        f"策略「{strategy.get('name')}」 (id {strategy.get('id')}, v{strategy.get('version')}) "
        f"状态 {strategy.get('status')}, 类型 {strategy.get('kind')}, 共 {len(legs)} 条腿。"
    ]
    for leg in legs:
        parts.append(
            f"{leg.get('side')} {leg.get('inst_id')} 目标权重 {leg.get('target_weight')}"
            f" ({leg.get('rationale') or '无说明'}) 。"
        )
    parts.append(f"审批记录 {approval_count} 条。")
    return " ".join(parts)


def backtest_citations(
    *,
    run: Mapping[str, Any],
    metrics: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    run_id = run.get("id")
    items: list[dict[str, Any]] = [
        citation(
            "backtest_run",
            f"GET /api/v1/backtests/{run_id}",
            run_id=run_id,
            strategy_id=run.get("strategy_id"),
            status=run.get("status"),
            window_start=(run.get("window") or {}).get("start"),
            window_end=(run.get("window") or {}).get("end"),
            bar=run.get("bar"),
            initial_capital=run.get("initial_capital"),
        )
    ]
    for metric in metrics:
        items.append(
            citation(
                "backtest_metric",
                f"GET /api/v1/backtests/{run_id}/metrics",
                run_id=run_id,
                name=metric.get("name"),
                value=metric.get("value"),
                unit=metric.get("unit"),
            )
        )
    return items


def metric_value(metrics: list[Mapping[str, Any]], name: str) -> str | None:
    for metric in metrics:
        if metric.get("name") == name:
            value = metric.get("value")
            return None if value is None else str(value)
    return None


def is_negative_run(metrics: list[Mapping[str, Any]]) -> bool:
    total = metric_value(metrics, "total_return")
    if total is None:
        return False
    try:
        return float(total) < 0
    except ValueError:
        return False


def has_growth_advice(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in GROWTH_ADVICE_TERMS)


def negative_note(metrics: list[Mapping[str, Any]]) -> str | None:
    if not is_negative_run(metrics):
        return None
    return "指标为负说明该参数组合在回测窗口内亏损, 不构成提高风险敞口的依据。"


def backtest_summary(
    *,
    run: Mapping[str, Any],
    metrics: list[Mapping[str, Any]],
) -> str:
    if not metrics:
        return f"数据不足: 回测 {run.get('id')} 没有指标记录。缺失项: backtest_metrics"
    window = run.get("window") or {}
    parts = [
        f"回测 {run.get('id')} 状态 {run.get('status')}, 窗口 "
        f"{window.get('start')} 至 {window.get('end')}, 周期 {run.get('bar')}, "
        f"初始资金 {run.get('initial_capital')}。"
    ]
    parts.append(
        "指标: "
        + ", ".join(
            f"{metric.get('name')}={metric.get('value')}{metric.get('unit') or ''}"
            for metric in metrics
        )
        + "。"
    )
    note = negative_note(metrics)
    if note is not None:
        parts.append(note)
    return " ".join(parts)


__all__ = [
    "GROWTH_ADVICE_TERMS",
    "backtest_citations",
    "backtest_summary",
    "has_growth_advice",
    "is_negative_run",
    "metric_value",
    "negative_note",
    "strategy_citations",
    "strategy_summary",
]

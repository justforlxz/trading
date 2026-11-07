"""用户自定义验证标准（纯函数）。

`criteria` 只描述「哪些指标、用什么比较符、阈值多少」，判定结果与 `passed`
一起回写 `backtest_run.params`，不做单独的 criteria 表。空 criteria 走默认标准
并标记 `default=true`——默认标准是产品口径，不是用户设定。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from app.backtest.errors import BacktestError

OPS: dict[str, str] = {
    ">=": "gte",
    "<=": "lte",
    ">": "gt",
    "<": "lt",
    "==": "eq",
}

DEFAULT_THRESHOLDS: tuple[dict[str, str], ...] = (
    {"name": "total_return", "op": ">=", "value": "0"},
    {"name": "max_drawdown", "op": "<=", "value": "0.5"},
)


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BacktestError(
            "backtest_criteria_invalid_value",
            f"invalid criteria threshold value: {value!r}",
        ) from exc


def _text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def normalize_thresholds(raw: Sequence[Mapping[str, Any]] | None) -> list[dict[str, str]]:
    """把请求里的标准规范化（Decimal 统一成最短十进制串），并做结构校验。"""

    if not raw:
        return [dict(item) for item in DEFAULT_THRESHOLDS]
    normalized: list[dict[str, str]] = []
    for item in raw:
        try:
            name = str(item["name"])
            op = str(item["op"])
        except (KeyError, TypeError) as exc:
            raise BacktestError(
                "backtest_criteria_invalid",
                "each threshold needs name and op",
            ) from exc
        if op not in OPS:
            raise BacktestError(
                "backtest_criteria_invalid_op",
                f"unsupported comparison operator: {op!r}",
                details={"op": op, "supported": sorted(OPS)},
            )
        if "value" not in item:
            raise BacktestError(
                "backtest_criteria_invalid",
                f"threshold {name!r} needs a value",
                details={"name": name},
            )
        normalized.append({"name": name, "op": op, "value": _text(_decimal(item["value"]))})
    return normalized


def _compare(actual: Decimal, op: str, threshold: Decimal) -> bool:
    kind = OPS[op]
    if kind == "gte":
        return actual >= threshold
    if kind == "lte":
        return actual <= threshold
    if kind == "gt":
        return actual > threshold
    if kind == "lt":
        return actual < threshold
    return actual == threshold


def evaluate(
    metrics: Mapping[str, Decimal],
    thresholds: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """逐条判定并汇总；未知指标直接报错，不静默跳过。"""

    default = not thresholds
    rows = normalize_thresholds(thresholds)
    results: list[dict[str, Any]] = []
    for row in rows:
        name = row["name"]
        if name not in metrics:
            raise BacktestError(
                "backtest_criteria_unknown_metric",
                f"unknown metric in criteria: {name!r}",
                details={"metric": name, "supported": sorted(metrics)},
            )
        threshold = Decimal(row["value"])
        actual = Decimal(metrics[name])
        results.append(
            {
                "name": name,
                "op": row["op"],
                "threshold": row["value"],
                "actual": _text(actual),
                "passed": _compare(actual, row["op"], threshold),
            }
        )
    return {
        "thresholds": rows,
        "results": results,
        "passed": all(item["passed"] for item in results),
        "default": default,
    }


__all__ = ["DEFAULT_THRESHOLDS", "OPS", "evaluate", "normalize_thresholds"]

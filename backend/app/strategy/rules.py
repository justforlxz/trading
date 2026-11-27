"""策略规则 JSON 的校验与规范化。

规则不是自然语言：每条入场/出场条件都是可序列化的比较语句。校验在这里做一次，
覆盖四件事：周期与方向取值、条件组的结构、指标与参数是否可用、未知字段直接拒绝
（不做静默丢弃）。仓位规则单独校验权重与数量。

条件本身的词汇（可选指标、运算符、出场附加项）由 `app.strategy.conditions` 定义，
这里只负责把它拼进规则、补上周期与方向。指标的计算与参数的默认值来自
`app.indicators` 注册表：规则里不复制算法，也不复制一份默认参数表。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from app.core import ValidationError
from app.strategy.conditions import normalize_group

__all__ = [
    "DIRECTIONS",
    "TIMEFRAMES",
    "canonical_json",
    "normalize_rule",
    "validate_position_sizing",
]

TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
DIRECTIONS = ("long_only", "short_only", "long_short")

_RULE_KEYS = frozenset({"timeframe", "direction", "entry", "exit", "position_sizing"})
_SIZING_KEYS = frozenset({"type", "weight", "max_positions"})


def canonical_json(value: Any) -> str:
    """规范化 JSON 文本：键排序、无多余空白，同内容两次序列化逐字相同。"""

    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def validate_position_sizing(value: Mapping[str, Any]) -> dict[str, Any]:
    """校验仓位规则：`weight` 在 0 到 1 之间，`max_positions` 是正整数。"""

    if not isinstance(value, Mapping):
        raise ValidationError("position_sizing 必须是 JSON 对象")
    unknown = sorted(set(value) - _SIZING_KEYS)
    if unknown:
        raise ValidationError(f"position_sizing 含未知字段: {', '.join(unknown)}")
    kind = value.get("type")
    if not isinstance(kind, str) or not kind.strip():
        raise ValidationError("position_sizing.type 必须是非空字符串")
    result: dict[str, Any] = {"type": kind.strip()}
    if "weight" in value:
        weight = value["weight"]
        if isinstance(weight, bool) or not isinstance(weight, int | float):
            raise ValidationError("position_sizing.weight 必须是数值")
        if not 0 <= float(weight) <= 1:
            raise ValidationError("position_sizing.weight 必须在 0 到 1 之间")
        result["weight"] = weight
    if "max_positions" in value:
        count = value["max_positions"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValidationError("position_sizing.max_positions 必须是正整数")
        result["max_positions"] = count
    return result


def normalize_rule(
    rule_json: Mapping[str, Any],
    *,
    timeframe: str,
    direction: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """校验规则并补齐周期/方向；返回（规范化规则，仓位规则）。

    规则里的 `timeframe` / `direction` 与版本字段是同一个事实：两者都提供时必须
    一致，缺省时补成版本字段，读回时规则本身始终能回答「按什么周期、朝哪个方向」。
    指标参数在这里补成完整参数表，存进规则的每一处指标都带齐参数，历史回测回放
    时不需要再猜默认值。
    """

    if not isinstance(rule_json, Mapping):
        raise ValidationError("rule_json 必须是 JSON 对象")
    unknown = sorted(set(rule_json) - _RULE_KEYS)
    if unknown:
        raise ValidationError(f"rule_json 含未知字段: {', '.join(unknown)}")

    _require_timeframe(timeframe)
    _require_direction(direction)
    stated_timeframe = rule_json.get("timeframe")
    if stated_timeframe is not None and stated_timeframe != timeframe:
        raise ValidationError(
            f"rule_json.timeframe 与版本周期不一致: {stated_timeframe!r} != {timeframe!r}"
        )
    stated_direction = rule_json.get("direction")
    if stated_direction is not None and stated_direction != direction:
        raise ValidationError(
            f"rule_json.direction 与版本方向不一致: {stated_direction!r} != {direction!r}"
        )

    entry = rule_json.get("entry")
    exit_ = rule_json.get("exit")
    if entry is None or exit_ is None:
        raise ValidationError("rule_json 必须同时包含 entry 与 exit")
    result: dict[str, Any] = {
        "timeframe": timeframe,
        "direction": direction,
        "entry": normalize_group(entry, "entry"),
        "exit": normalize_group(exit_, "exit", exit_group=True),
    }

    sizing = rule_json.get("position_sizing")
    normalized_sizing = None if sizing is None else validate_position_sizing(sizing)
    if normalized_sizing is not None:
        result["position_sizing"] = normalized_sizing
    return result, normalized_sizing


def _require_timeframe(value: str) -> None:
    if value not in TIMEFRAMES:
        raise ValidationError(f"不支持的周期 {value!r}; 支持: {', '.join(TIMEFRAMES)}")


def _require_direction(value: str) -> None:
    if value not in DIRECTIONS:
        raise ValidationError(f"不支持的方向 {value!r}; 支持: {', '.join(DIRECTIONS)}")

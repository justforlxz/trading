"""策略规则 JSON 的校验与规范化。

规则不是自然语言：每条入场/出场条件都是可序列化的比较或止损语句。校验在这里做
一次，覆盖四件事：周期与方向取值、指标名确实在 `app.indicators` 注册表里、比较符
只有五种、未知字段直接拒绝（不做静默丢弃）。仓位规则单独校验权重与数量。

指标表达式采用 `MA(20)`、`RSI(14)`、`MACD(12,26,9)` 这种写法。注册表里的名字是
小写（`sma` / `rsi` / `macd`），这里只做常见大写别名到注册名的映射；别名不属于
第二套指标体系，计算仍由注册表提供。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from app.core import ValidationError
from app.indicators import list_definitions

__all__ = [
    "DIRECTIONS",
    "OPERATORS",
    "TIMEFRAMES",
    "canonical_json",
    "normalize_rule",
    "validate_position_sizing",
]

TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
DIRECTIONS = ("long_only", "short_only", "long_short")
OPERATORS = (">", ">=", "<", "<=", "==")

# 常见的展示名 → 注册表名。注册名本身直接接受（大小写不敏感），所以注册表新增指标
# 不需要同步这张表；这里只放与注册名不同的展示写法。
_INDICATOR_ALIASES = {
    "ma": "sma",
    "boll": "bollinger",
    "vol_ma": "volume_ma",
}

_EXPRESSION = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*([0-9]+(?:\s*,\s*[0-9]+)*)?\s*\)\s*$"
)
_RULE_KEYS = frozenset({"timeframe", "direction", "entry", "exit", "position_sizing"})
_GROUP_KEYS = frozenset({"all", "any"})
_CONDITION_KEYS = frozenset({"left", "op", "right"})
_STOP_KEYS = frozenset({"type", "value"})
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
        "entry": _validate_group(entry, "entry"),
        "exit": _validate_group(exit_, "exit"),
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


def _validate_group(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"rule_json.{path} 必须是 JSON 对象")
    unknown = sorted(set(value) - _GROUP_KEYS)
    if unknown:
        raise ValidationError(f"rule_json.{path} 含未知字段: {', '.join(unknown)}")
    keys = [key for key in _GROUP_KEYS if key in value]
    if len(keys) != 1:
        raise ValidationError(f"rule_json.{path} 必须且只能包含 all 或 any")
    key = keys[0]
    conditions = value[key]
    if not isinstance(conditions, list) or not conditions:
        raise ValidationError(f"rule_json.{path}.{key} 必须是非空数组")
    return {
        key: [
            _validate_condition(item, f"{path}.{key}[{index}]")
            for index, item in enumerate(conditions)
        ]
    }


def _validate_condition(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"rule_json.{path} 必须是 JSON 对象")
    if "type" in value:
        unknown = sorted(set(value) - _STOP_KEYS)
        if unknown:
            raise ValidationError(f"rule_json.{path} 含未知字段: {', '.join(unknown)}")
        if value.get("type") != "drawdown_stop":
            raise ValidationError(f"rule_json.{path} 不支持的条件类型: {value.get('type')!r}")
        stop = value.get("value")
        if isinstance(stop, bool) or not isinstance(stop, int | float) or float(stop) <= 0:
            raise ValidationError(f"rule_json.{path}.value 必须是正数")
        return {"type": "drawdown_stop", "value": stop}

    unknown = sorted(set(value) - _CONDITION_KEYS)
    if unknown:
        raise ValidationError(f"rule_json.{path} 含未知字段: {', '.join(unknown)}")
    missing = sorted(_CONDITION_KEYS - set(value))
    if missing:
        raise ValidationError(f"rule_json.{path} 缺少字段: {', '.join(missing)}")
    operator = value.get("op")
    if operator not in OPERATORS:
        raise ValidationError(
            f"rule_json.{path}.op 不支持: {operator!r}; 支持: {', '.join(OPERATORS)}"
        )
    return {
        "left": _validate_operand(value.get("left"), f"{path}.left"),
        "op": operator,
        "right": _validate_operand(value.get("right"), f"{path}.right"),
    }


def _validate_operand(value: Any, path: str) -> Any:
    if isinstance(value, bool):
        raise ValidationError(f"rule_json.{path} 不接受布尔值")
    if isinstance(value, int | float):
        return value
    if not isinstance(value, str):
        raise ValidationError(f"rule_json.{path} 必须是数值或指标表达式")
    match = _EXPRESSION.match(value)
    if match is None:
        raise ValidationError(f"rule_json.{path} 的指标表达式格式应为 NAME(参数): {value!r}")
    raw_name = match.group(1).lower()
    name = _INDICATOR_ALIASES.get(raw_name, raw_name)
    definition = {item.name: item for item in list_definitions()}.get(name)
    if definition is None:
        raise ValidationError(f"rule_json.{path} 的指标未注册: {match.group(1)!r}")
    raw_args = match.group(2)
    args = [] if not raw_args else [int(item.strip()) for item in raw_args.split(",")]
    if len(args) != len(definition.params):
        raise ValidationError(
            f"rule_json.{path} 的指标 {match.group(1)} 需要 {len(definition.params)} 个参数, "
            f"实际 {len(args)} 个"
        )
    if any(arg < 1 for arg in args):
        raise ValidationError(f"rule_json.{path} 的指标参数必须是正整数")
    return value.strip()

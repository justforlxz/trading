"""回测规则的条件表达式：可选指标清单、条件校验与逐根求值。

可选指标由这里的一份清单定义（用户确认的八个）。参数与输出仍取自 `app.indicators`
注册表：同一个指标只有一份计算实现，这里不复制算法，也不复制参数的默认值与取值
范围。清单里写的是「回测条件的左值能用哪几个指标」，不是第二套指标体系。

求值是纯函数：入参是已规范化的条件组与已收盘 K 线序列，出参是每根 K 线一个布尔
值。第 i 根只读第 i 根与第 i-1 根，`cross_above` / `cross_below` 因此不会看到后面
的 K 线，回测不会因为「后面涨了」而改变前面的信号。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.core import Bar, InvariantViolation, ValidationError
from app.indicators import Param, ParamValue, compute, definition

__all__ = [
    "EXIT_EXTRA_KEYS",
    "LOGIC",
    "OPERATORS",
    "ConditionIndicator",
    "ConditionOutput",
    "condition_catalog",
    "normalize_group",
    "signal_series",
]

#: 条件里的比较方式：下标值与常量之间只有大小关系与穿越两种表达。
OPERATORS = ("lt", "gt", "cross_above", "cross_below")

#: 一组条件之间的关系：全部满足 / 任一满足。
LOGIC = ("and", "or")

#: 出场在条件组之外还支持的附加项：止盈百分比、止损百分比、反向信号。
EXIT_EXTRA_KEYS = ("take_profit_pct", "stop_loss_pct", "reverse_signal")

#: 常见展示写法 → 注册表名。注册表名本身直接接受，所以注册表新增指标不需要同步
#: 这张表；这里只放与注册名不同的写法。
_ALIASES = {"ma": "sma", "boll": "bollinger"}

#: 清单里的指标展示名与输出展示名。只影响前端下拉怎么显示，`name` 才是写进规则的
#: 值；参数、输出列与最小 K 线数一律取自注册表，不在这里重复声明。
_TITLES: dict[str, str] = {
    "rsi": "RSI",
    "close": "收盘价",
    "sma": "MA",
    "atr": "ATR",
    "volume": "成交量",
    "change_24h": "24H 涨跌幅",
    "macd": "MACD",
    "bollinger": "布林带",
}

_OUTPUT_TITLES: dict[str, tuple[tuple[str, str], ...]] = {
    "rsi": (("rsi", "RSI"),),
    "close": (("close", "收盘价"),),
    "sma": (("sma", "均线"),),
    "atr": (("atr", "ATR"),),
    "volume": (("volume", "成交量"),),
    "change_24h": (("change_24h", "涨跌幅"),),
    "macd": (("macd", "DIF"), ("signal", "DEA"), ("hist", "柱")),
    "bollinger": (("upper", "上轨"), ("middle", "中轨"), ("lower", "下轨")),
}


@dataclass(frozen=True, slots=True)
class ConditionOutput:
    """条件左值能选到的一个输出列：`name` 写进规则，`title` 用于展示。"""

    name: str
    title: str


@dataclass(frozen=True, slots=True)
class ConditionIndicator:
    """回测条件可用的一个指标；参数与输出来自注册表，不在本模块重写。"""

    name: str
    title: str
    summary: str
    outputs: tuple[ConditionOutput, ...]
    params: tuple[Param, ...]
    min_bars: int


def condition_catalog() -> tuple[ConditionIndicator, ...]:
    """八个可选指标，顺序与用户确认的清单一致。

    输出列必须与注册表声明逐项相同：少了或多了一列都是清单与实现脱节，属于装配
    错误，直接抛 `InvariantViolation` 而不是悄悄只发布交集。
    """

    items: list[ConditionIndicator] = []
    for name, titles in _OUTPUT_TITLES.items():
        spec = definition(name)
        declared = tuple(output for output, _ in titles)
        if declared != spec.outputs:
            raise InvariantViolation(
                f"条件清单里 {name} 的输出 {declared} 与注册表声明 {spec.outputs} 不一致"
            )
        items.append(
            ConditionIndicator(
                name=spec.name,
                title=_TITLES[name],
                summary=spec.summary,
                outputs=tuple(ConditionOutput(name=key, title=title) for key, title in titles),
                params=spec.params,
                min_bars=spec.min_length,
            )
        )
    return tuple(items)


def normalize_group(value: Any, path: str, *, exit_group: bool = False) -> dict[str, Any]:
    """校验一组条件并补全指标参数，返回可以存进 `rule_json` 的规范化结果。

    `path` 只用于报错定位（`entry` / `exit`）；出场组额外接受止盈、止损与反向信号。
    """

    if not isinstance(value, Mapping):
        raise ValidationError(f"rule_json.{path} 必须是 JSON 对象")
    allowed = {"logic", "conditions"} | (set(EXIT_EXTRA_KEYS) if exit_group else set())
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValidationError(f"rule_json.{path} 含未知字段: {', '.join(unknown)}")
    missing = sorted({"logic", "conditions"} - set(value))
    if missing:
        raise ValidationError(f"rule_json.{path} 缺少字段: {', '.join(missing)}")

    logic = value["logic"]
    if logic not in LOGIC:
        raise ValidationError(f"rule_json.{path}.logic 只能是 {', '.join(LOGIC)}, 实际 {logic!r}")
    conditions = value["conditions"]
    if not isinstance(conditions, list) or not conditions:
        raise ValidationError(f"rule_json.{path}.conditions 必须是非空数组")

    result: dict[str, Any] = {
        "logic": logic,
        "conditions": [
            _condition(item, f"{path}.conditions[{index}]") for index, item in enumerate(conditions)
        ],
    }
    if exit_group:
        result.update(_exit_extras(value, path))
    return result


def signal_series(group: Mapping[str, Any], bars: Sequence[Bar]) -> tuple[bool, ...]:
    """把一组已规范化的条件逐根求值，返回与 K 线等长的布尔序列。

    第 i 根只用第 i 根与第 i-1 根：大小比较只看当前值，穿越要求「上一根不满足、
    当前根满足」。第一根没有上一根，任何穿越都不成立。指标值未定义的位置（热身
    区间、没有基期的涨跌幅）一律按不成立处理。
    """

    columns = [_condition_signals(condition, bars) for condition in group["conditions"]]
    combine = all if group["logic"] == "and" else any
    return tuple(combine(values) for values in zip(*columns, strict=True))


def _condition_signals(condition: Mapping[str, Any], bars: Sequence[Bar]) -> tuple[bool, ...]:
    left = _values(condition["left"], bars)
    right = _values(condition["right"], bars)
    return tuple(_holds(condition["op"], index, left, right) for index in range(len(bars)))


def _values(operand: Mapping[str, Any], bars: Sequence[Bar]) -> tuple[Decimal | None, ...]:
    """一个操作数在每根 K 线上的取值；常量展开成等长的重复值。

    K 线不足以让指标成形时注册表返回空序列，这里补成等长的 `None`，调用方不必为
    「热身区间」单独判断长度。
    """

    if "value" in operand:
        return (Decimal(str(operand["value"])),) * len(bars)
    output = operand.get("output")
    if output is None:
        raise ValidationError(f"条件里的指标 {operand['indicator']} 缺少 output")
    params = {key: item for key, item in operand.items() if key not in {"indicator", "output"}}
    series = compute(operand["indicator"], bars, params)
    if len(series.points) != len(bars):
        return (None,) * len(bars)
    return tuple(point.values[output] for point in series.points)


def _holds(
    operator: str,
    index: int,
    left: tuple[Decimal | None, ...],
    right: tuple[Decimal | None, ...],
) -> bool:
    current_left, current_right = left[index], right[index]
    if current_left is None or current_right is None:
        return False
    if operator == "lt":
        return current_left < current_right
    if operator == "gt":
        return current_left > current_right
    if index == 0:
        return False
    previous_left, previous_right = left[index - 1], right[index - 1]
    if previous_left is None or previous_right is None:
        return False
    if operator == "cross_above":
        return previous_left <= previous_right and current_left > current_right
    return previous_left >= previous_right and current_left < current_right


def _condition(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"rule_json.{path} 必须是 JSON 对象")
    unknown = sorted(set(value) - {"left", "op", "right"})
    if unknown:
        raise ValidationError(f"rule_json.{path} 含未知字段: {', '.join(unknown)}")
    missing = sorted({"left", "op", "right"} - set(value))
    if missing:
        raise ValidationError(f"rule_json.{path} 缺少字段: {', '.join(missing)}")
    operator = value["op"]
    if operator not in OPERATORS:
        raise ValidationError(
            f"rule_json.{path}.op 不支持: {operator!r}; 支持: {', '.join(OPERATORS)}"
        )
    return {
        "left": _operand(value["left"], f"{path}.left", constant=False),
        "op": operator,
        "right": _operand(value["right"], f"{path}.right", constant=True),
    }


def _operand(value: Any, path: str, *, constant: bool) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"rule_json.{path} 必须是 JSON 对象")
    if "value" in value:
        if not constant:
            raise ValidationError(f"rule_json.{path} 不能是常量: 左值必须是指标")
        if len(value) != 1:
            raise ValidationError(f"rule_json.{path} 写成常量时不能再带其它字段")
        return {"value": _number(value["value"], f"{path}.value")}
    if "indicator" not in value:
        raise ValidationError(f"rule_json.{path} 必须包含 indicator, 或右值用 value 表示常量")
    return _indicator(value, path)


def _number(value: Any, path: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValidationError(f"rule_json.{path} 必须是数值")
    return value


def _indicator(value: Mapping[str, Any], path: str) -> dict[str, Any]:
    """校验指标操作数并补全参数：未知参数、越界取值、缺失输出都在这里拦下。"""

    raw = value["indicator"]
    if not isinstance(raw, str) or not raw.strip():
        raise ValidationError(f"rule_json.{path}.indicator 必须是非空字符串")
    written = raw.strip().lower()
    name = _ALIASES.get(written, written)
    catalog = {item.name: item for item in condition_catalog()}
    spec = catalog.get(name)
    if spec is None:
        raise ValidationError(
            f"rule_json.{path}.indicator 不在回测可用指标里: {raw!r}; 可用: {', '.join(catalog)}"
        )

    unknown = sorted(set(value) - {"indicator", "output"} - {param.name for param in spec.params})
    if unknown:
        raise ValidationError(f"rule_json.{path} 含未知字段: {', '.join(unknown)}")
    params: dict[str, ParamValue] = {
        key: item for key, item in value.items() if key not in {"indicator", "output"}
    }
    try:
        # 空 K 线只会走参数校验这一步：注册表先补默认值并检查类型与范围，再把
        # 「K 线不足」翻译成空序列。参数校验因此不需要另写一份。
        resolved = compute(name, (), params).params
    except ValidationError as exc:
        raise ValidationError(f"rule_json.{path}: {exc}") from None

    output = _output(value.get("output"), spec, path)
    return {"indicator": name, "output": output, **resolved}


def _output(value: Any, spec: ConditionIndicator, path: str) -> str:
    names = [item.name for item in spec.outputs]
    if value is None:
        if len(names) == 1:
            return names[0]
        raise ValidationError(
            f"rule_json.{path}.output 必须指定: {spec.name} 有多个输出 ({', '.join(names)})"
        )
    if value not in names:
        raise ValidationError(
            f"rule_json.{path}.output 不支持: {value!r}; 可用: {', '.join(names)}"
        )
    return value


def _exit_extras(value: Mapping[str, Any], path: str) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    for key in ("take_profit_pct", "stop_loss_pct"):
        if key in value:
            number = _number(value[key], f"{path}.{key}")
            if number <= 0:
                raise ValidationError(f"rule_json.{path}.{key} 必须是正数")
            extras[key] = number
    if "reverse_signal" in value:
        flag = value["reverse_signal"]
        if not isinstance(flag, bool):
            raise ValidationError(f"rule_json.{path}.reverse_signal 必须是布尔值")
        extras["reverse_signal"] = flag
    return extras

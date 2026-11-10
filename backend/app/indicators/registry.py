"""指标注册表：登记声明与实现，按名解析参数并计算。

注册复用 `app.core` 的注册表原语：指标、策略、provider 共用同一套「按 kind 取名
取实现」，不必各写一份发现机制。

`compute` 是纯函数：只读入参，不写缓存；同一组入参重复调用结果相等。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from app.core import Bar, ValidationError, get, list_names, register
from app.indicators.types import IndicatorDefinition, Param, ParamValue, Series

Compute = Callable[[Sequence[Bar], Mapping[str, ParamValue]], Series]
Warmup = Callable[[Mapping[str, ParamValue]], int]
Check = Callable[[Mapping[str, ParamValue]], None]


@dataclass(frozen=True, slots=True)
class _Entry:
    """注册表里真正存的东西：声明 + 热身长度 + 计算函数 + 可选的跨参数检查。"""

    definition: IndicatorDefinition
    warmup: Warmup
    compute: Compute
    check: Check | None = None


def register_indicator(
    definition: IndicatorDefinition,
    warmup: Warmup,
    compute: Compute,
    check: Check | None = None,
) -> None:
    """登记一个指标；同名重复登记由注册表原语抛 `InvariantViolation`。"""

    register("indicator", definition.name)(
        _Entry(definition=definition, warmup=warmup, compute=compute, check=check)
    )


def _entry(name: str) -> _Entry:
    return cast(_Entry, get("indicator", name))


def _checked(spec: Param, value: ParamValue) -> ParamValue:
    """校验单个参数的类型与范围，返回规范化后的值（浮点参数统一成 float）。"""

    if spec.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(f"{spec.name} 必须是整数")
        number: ParamValue = value
    else:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValidationError(f"{spec.name} 必须是数值")
        number = float(value)
    if not spec.minimum <= number <= spec.maximum:
        raise ValidationError(
            f"{spec.name} 必须在 {spec.minimum} 到 {spec.maximum} 之间, 实际 {number}"
        )
    return number


def _resolve_params(
    definition: IndicatorDefinition, params: Mapping[str, ParamValue] | None
) -> dict[str, ParamValue]:
    """把调用方给的部分参数补成完整参数表，未知名字与越界值都按参数不合法处理。"""

    supplied = dict(params or {})
    unknown = sorted(set(supplied) - {spec.name for spec in definition.params})
    if unknown:
        raise ValidationError(f"{definition.name} 不支持参数: {', '.join(unknown)}")
    return {
        spec.name: _checked(spec, supplied.get(spec.name, spec.default))
        for spec in definition.params
    }


def compute(
    name: str, bars: Sequence[Bar], params: Mapping[str, ParamValue] | None = None
) -> Series:
    """按名字算指标；K 线不足最小长度时返回空 `points`，不抛异常。"""

    entry = _entry(name)
    resolved = _resolve_params(entry.definition, params)
    if entry.check is not None:
        entry.check(resolved)
    if len(bars) < entry.warmup(resolved):
        return Series(name=entry.definition.name, params=resolved, points=())
    return entry.compute(bars, resolved)


def definition(name: str) -> IndicatorDefinition:
    """取某个指标的声明；未登记的名字按参数不合法处理。"""

    return _entry(name).definition


def list_definitions() -> list[IndicatorDefinition]:
    """全部已登记指标的声明，按名字字典序。"""

    return [definition(name) for name in list_names("indicator")]

"""策略参数 schema 校验。

策略声明自己接受哪些参数（名字、类型、默认值、闭区间范围），本模块把调用方给的
部分参数补成完整参数表。校验只在入口做一次：越界、类型不对、写了不存在的参数都
按参数不合法处理，错误信息以字段名开头或列出字段名，调用方据此能直接定位到界面上的
某个输入框。

参数规格复用指标模块的 `Param`：两者的语义相同（可调的整数/浮点参数 + 范围），
没有第二套定义的必要。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.core import InvariantViolation, ValidationError
from app.indicators import Param, ParamValue

__all__ = ["resolve_params"]


def _checked(spec: Param, value: ParamValue) -> ParamValue:
    """校验单个参数的类型与范围，返回规范化后的值（浮点参数统一成 float）。"""

    if spec.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(f"{spec.name} 必须是整数, 实际 {value!r}")
        number: ParamValue = value
    else:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValidationError(f"{spec.name} 必须是数值, 实际 {value!r}")
        number = float(value)
    if not spec.minimum <= number <= spec.maximum:
        raise ValidationError(
            f"{spec.name} 必须在 {spec.minimum} 到 {spec.maximum} 之间, 实际 {number}"
        )
    return number


def resolve_params(
    schema: Sequence[Param], supplied: Mapping[str, ParamValue] | None = None
) -> dict[str, ParamValue]:
    """把调用方给的部分参数补成完整参数表。

    schema 里重复的同名参数属于装配错误（`InvariantViolation`）：那时「取哪个默认值」
    没有唯一答案，不能按参数不合法糊过去。
    """

    names = [spec.name for spec in schema]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise InvariantViolation(f"参数 schema 中出现重复字段:{', '.join(duplicates)}")

    provided = dict(supplied or {})
    unknown = sorted(set(provided) - set(names))
    if unknown:
        raise ValidationError(f"不支持的参数:{', '.join(unknown)}")

    return {spec.name: _checked(spec, provided.get(spec.name, spec.default)) for spec in schema}

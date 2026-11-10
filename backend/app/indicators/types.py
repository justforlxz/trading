"""指标模块的值对象：参数规格、指标声明、输出点与序列。

这些结构同时是 API 目录契约（`app/api/schemas/indicators.py`）的数据来源，
字段一一对应：`min_length` 在接口层叫 `min_bars`，其余同名。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

# 指标参数只允许整数与浮点数：字符串参数会让「范围校验」失去意义。
ParamValue = int | float

ParamKind = Literal["int", "float"]


@dataclass(frozen=True, slots=True)
class Param:
    """一个可调参数的声明：名字、类型、默认值与闭区间范围。"""

    name: str
    title: str
    kind: ParamKind
    default: ParamValue
    minimum: float
    maximum: float


@dataclass(frozen=True, slots=True)
class IndicatorDefinition:
    """指标的对外声明：输入哪些 K 线字段、输出哪些列、需要多少根 K 线。

    `inputs` 是 `Bar` 的字段名（`close` / `high` / ...），告诉调用方缺哪些数据
    就不能算；`min_length` 是**默认参数**下需要的最少 K 线数，换参数后的实际
    要求由各指标自己的热身长度给出，并由 `compute` 统一裁剪。
    """

    name: str
    title: str
    summary: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    params: tuple[Param, ...]
    min_length: int


@dataclass(frozen=True, slots=True)
class Point:
    """某个 K 线时刻上的一行输出；窗口尚未成形的列是 `None`。"""

    time: datetime
    values: dict[str, Decimal | None]


@dataclass(frozen=True, slots=True)
class Series:
    """一次指标计算的完整结果：与输入 K 线逐根对齐，`None` 表示该点未定义。"""

    name: str
    params: dict[str, ParamValue]
    points: tuple[Point, ...]

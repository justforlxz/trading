"""两类组合模板：把基础组件拼成目标组合，只此两类。

模板是「怎么组合」的唯一出口，因此配权、选腿数与多空形态都写在这里，组件那边只管
单标的判断。模板数量固定两类（方向性、相对价值），不因为组件有六个就多造模板：组件
是可复用零件，模板是产品化的组合方式。

模板与组件一样只读视图，参数在构造时给定，`build` 只接收视图一个参数。
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.core import InvariantViolation

__all__ = ["Directional", "RelativeValue", "mean"]


def mean(values: Sequence[Decimal]) -> Decimal:
    """算术平均：空序列没有平均值，直接报错而不是返回 0。"""

    if not values:
        raise InvariantViolation("空序列没有平均值")
    return sum(values) / Decimal(len(values))


# 导入即登记两类模板，放在文件末尾（与组件包同样的理由）。
from app.strategy.templates.directional import Directional  # noqa: E402
from app.strategy.templates.relative_value import RelativeValue  # noqa: E402

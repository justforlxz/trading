"""目标组合的约束：组合必须满足的五项边界。

约束只判断、不改写：越限直接抛 `RiskBlocked`，绝不把权重压回上限。静默截断会让
「策略要 0.6、实际持有 0.5」这件事在日志里看不出来，事后分不清是策略过激还是有人
改过仓位。

五项边界是纯数据，与策略、账户、行情都无关，因此可以逐条断言。`RiskBlocked` 的
`rule` 用字段名，上层既能按规则统计拒绝分布，又能把原因原样展示给用户。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from app.core import RiskBlocked, ValidationError

if TYPE_CHECKING:  # 只为类型标注；运行期由 `target` 导入本模块，反向导入会成环。
    from app.strategy.target import TargetLeg

__all__ = ["PortfolioConstraints", "check_constraints", "check_upper_bounds"]

_LONG = "long"

_WEIGHT_FIELDS = ("max_leg_weight", "max_long_weight", "max_short_weight", "min_leg_weight")


@dataclass(frozen=True, slots=True)
class PortfolioConstraints:
    """目标组合的五项边界：单标的上限、多空各自上限、单腿权重下限、腿数上限。

    `min_leg_weight` 允许为 0，表示不设下界；它不能大于 `max_leg_weight`，否则任何
    权重都同时「太小」和「太大」。
    """

    max_leg_weight: Decimal
    max_long_weight: Decimal
    max_short_weight: Decimal
    min_leg_weight: Decimal
    max_legs: int

    def __post_init__(self) -> None:
        for name in _WEIGHT_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, Decimal):
                raise ValidationError(f"{name} 必须是 Decimal, 实际 {type(value).__name__}")
            if not value.is_finite() or value < 0:
                raise ValidationError(f"{name} 必须是非负有限数, 实际 {value}")
        if not isinstance(self.max_legs, int) or self.max_legs < 1:
            raise ValidationError(f"max_legs 必须是正整数, 实际 {self.max_legs!r}")
        if self.min_leg_weight > self.max_leg_weight:
            raise ValidationError(
                f"min_leg_weight {self.min_leg_weight} 不能大于 "
                f"max_leg_weight {self.max_leg_weight}"
            )


def check_upper_bounds(legs: Iterable[TargetLeg], constraints: PortfolioConstraints) -> None:
    """只判四项上限：腿数、单标的、多头之和、空头之和。

    上限在看请求权重的阶段就要判：超额请求本来就不合规，而缩放只会把权重变小，
    只判缩放后的结果等于给超额请求留了一条捷径。单腿权重下限不在这里，理由见
    `check_constraints`。

    腿权重是大小（`TargetLeg` 不接收负权重），方向由 `side` 单独表达，因此这里
    不需要取绝对值。
    """

    ordered = tuple(legs)
    if len(ordered) > constraints.max_legs:
        raise RiskBlocked("max_legs", f"腿数 {len(ordered)} 超过上限 {constraints.max_legs}")

    long_total = Decimal(0)
    short_total = Decimal(0)
    for leg in ordered:
        weight = leg.target_weight
        if weight > constraints.max_leg_weight:
            raise RiskBlocked(
                "max_leg_weight",
                f"{leg.product_key} 的权重 {weight} 超过单标的上限 {constraints.max_leg_weight}",
            )
        if leg.side == _LONG:
            long_total += weight
        else:
            short_total += weight

    if long_total > constraints.max_long_weight:
        raise RiskBlocked(
            "max_long_weight",
            f"多头权重之和 {long_total} 超过上限 {constraints.max_long_weight}",
        )
    if short_total > constraints.max_short_weight:
        raise RiskBlocked(
            "max_short_weight",
            f"空头权重之和 {short_total} 超过上限 {constraints.max_short_weight}",
        )


def check_constraints(legs: Iterable[TargetLeg], constraints: PortfolioConstraints) -> None:
    """判全部五项边界；只用于归一化之后的最终权重。

    单腿权重下限不参与请求阶段的判定：权重是相对比例，两腿各 0.2（合计 0.4）配单腿
    权重下限 0.25，归一化后是 0.5 与 0.5，完全合规；在请求阶段按 0.2 判下限会把这
    种合法输入误拒，给出的原因还与真实情况不符。上限相反：缩放只会把权重变小，
    只判缩放后的结果拦不住超额请求，因此请求阶段也要判，见 `check_upper_bounds`。
    """

    ordered = tuple(legs)
    check_upper_bounds(ordered, constraints)
    for leg in ordered:
        if leg.target_weight < constraints.min_leg_weight:
            raise RiskBlocked(
                "min_leg_weight",
                f"{leg.product_key} 的权重 {leg.target_weight} 低于单腿权重下限 "
                f"{constraints.min_leg_weight}",
            )

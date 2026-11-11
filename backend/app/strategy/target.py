"""目标组合：策略对外的形状。

策略不说「对某个标的做什么动作」，只说「我要在某个产品上持有多少权重、方向是
多还是空、为什么」。数量换算、下单、账户与风控都不在这里：这一层只描述目标状态。

`net_exposure` 由各腿推导，不接受调用方传入：两个来源迟早会分叉，而「多头权重之和
减空头权重之和」只有一个正确答案。权重用 `Decimal`，与对外契约的十进制文本一致，
相加不经过浮点。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.core import ValidationError

__all__ = ["TargetLeg", "TargetPortfolio"]

_SIDES = frozenset({"long", "short"})


@dataclass(frozen=True, slots=True)
class TargetLeg:
    """组合中的一条腿：产品键 + 方向 + 目标权重 + 依据。

    `target_weight` 是权重的大小（占组合资金的比例），方向由 `side` 单独表达，不用
    权重符号再编码一次方向。`reason` 记录这条腿的产生依据，供人工审核与复盘。
    """

    product_key: str
    side: str
    target_weight: Decimal
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.product_key, str) or not self.product_key.strip():
            raise ValidationError("目标腿的 product_key 不能为空")
        if self.side not in _SIDES:
            raise ValidationError(f"目标腿的 side 必须是 {sorted(_SIDES)}, 实际 {self.side!r}")
        if not isinstance(self.target_weight, Decimal):
            raise ValidationError(
                f"目标腿的 target_weight 必须是 Decimal, 实际 {type(self.target_weight).__name__}"
            )
        if not self.target_weight.is_finite() or self.target_weight < 0:
            raise ValidationError(
                f"目标腿的 target_weight 必须是非负有限数, 实际 {self.target_weight}"
            )


@dataclass(frozen=True, slots=True)
class TargetPortfolio:
    """某一时点的目标组合；腿为空表示「不持有任何仓位」。

    同一个产品只允许一条腿：方向已经由 `side` 表达，同一个产品出现两条腿说明策略
    自相矛盾，多空冲突的处理不属于这一层，因此直接拒绝而不是悄悄相加。

    腿序列在构造时转成元组，`net_exposure` 同时由腿推导出来，因此不存在「权重改了
    但敞口没改」的实例。
    """

    as_of: datetime
    legs: tuple[TargetLeg, ...]
    net_exposure: Decimal = field(init=False)

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValidationError("目标组合的 as_of 必须带时区")

        legs = tuple(self.legs)
        seen: set[str] = set()
        exposure = Decimal(0)
        for leg in legs:
            if not isinstance(leg, TargetLeg):
                raise ValidationError(
                    f"目标组合的 legs 只能是 TargetLeg, 实际 {type(leg).__name__}"
                )
            if leg.product_key in seen:
                raise ValidationError(f"目标组合的 legs 中 product_key 重复:{leg.product_key}")
            seen.add(leg.product_key)
            exposure += leg.target_weight if leg.side == "long" else -leg.target_weight

        object.__setattr__(self, "legs", legs)
        object.__setattr__(self, "net_exposure", exposure)

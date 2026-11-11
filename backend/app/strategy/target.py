"""目标组合：策略对外的形状，以及把它换算成可执行数量。

策略不说「对某个标的做什么动作」，只说「我要在某个产品上持有多少权重、方向是
多还是空、为什么」。策略只产出权重；组合生成（`build_target`）负责把权重归一化到
1 并逐条比对约束，数量换算（`target_quantity`）负责按类别换成本次能下的数量。下单、
账户与风控都不在这里。

`net_exposure` 由各腿推导，不接受调用方传入：两个来源迟早会分叉，而「多头权重之和
减空头权重之和」只有一个正确答案。权重用 `Decimal`，与对外契约的十进制文本一致，
相加不经过浮点。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal

from app.core import InstrumentRef, ValidationError
from app.instrument import trading_rules
from app.strategy.constraints import (
    PortfolioConstraints,
    check_constraints,
    check_upper_bounds,
)

__all__ = [
    "TargetLeg",
    "TargetPortfolio",
    "TargetQuantity",
    "build_target",
    "normalize_weights",
    "target_quantity",
]

_SIDES = frozenset({"long", "short"})

# 契约里的数量单位：现货是标的币数量，永续是合约张数。公式由单位决定，不看类别。
_UNIT_BASE = "base"
_UNIT_CONTRACT = "contract"


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

        legs = _legs(self.legs)
        seen: set[str] = set()
        exposure = Decimal(0)
        for leg in legs:
            if leg.product_key in seen:
                raise ValidationError(f"目标组合的 legs 中 product_key 重复:{leg.product_key}")
            seen.add(leg.product_key)
            exposure += leg.target_weight if leg.side == "long" else -leg.target_weight

        object.__setattr__(self, "legs", legs)
        object.__setattr__(self, "net_exposure", exposure)


@dataclass(frozen=True, slots=True)
class TargetQuantity:
    """一条腿换算出的下单数量：`{inst_id, qty, unit}` 加舍弃数量。

    `unit` 取标的类别的 `qty_unit`：`base` 是标的币数量，`contract` 是合约张数。两种
    形态在外部表现上是同一个形状，上层拿到之后不必再问类别。

    `discarded` 是按 `lot_size` 向下取整时舍掉的数量（理论值减实际值）。记录它是因为
    「差一点点没买满」与「差一整张」是两回事，复盘与对账都需要看见这个差。
    """

    inst_id: str
    qty: Decimal
    unit: str
    discarded: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.inst_id, str) or not self.inst_id.strip():
            raise ValidationError("目标数量的 inst_id 不能为空")
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValidationError("目标数量的 unit 不能为空")
        for name in ("qty", "discarded"):
            value = getattr(self, name)
            if not isinstance(value, Decimal):
                raise ValidationError(
                    f"目标数量的 {name} 必须是 Decimal, 实际 {type(value).__name__}"
                )
            if not value.is_finite() or value < 0:
                raise ValidationError(f"目标数量的 {name} 必须是非负有限数, 实际 {value}")


def _legs(legs: Iterable[TargetLeg]) -> tuple[TargetLeg, ...]:
    """把入参固化成元组，并拒绝混进来的非 `TargetLeg` 项。

    先在这里判一次，后面的约束检查与归一化就可以放心读属性，不必各自再判一遍。
    """

    ordered = tuple(legs)
    for leg in ordered:
        if not isinstance(leg, TargetLeg):
            raise ValidationError(f"目标组合的 legs 只能是 TargetLeg, 实际 {type(leg).__name__}")
    return ordered


def normalize_weights(legs: Iterable[TargetLeg]) -> tuple[TargetLeg, ...]:
    """把各腿权重的绝对值之和缩放到 1。

    权重是相对比例：策略给出 0.3 与 0.1，表示多头占四分之三、空头占四分之一。缩放在
    `Decimal` 上做，不经过浮点。全部为 0 时没有比例可依，拒绝而不是编一个权重出来。
    """

    ordered = _legs(legs)
    if not ordered:
        return ordered

    total = sum((leg.target_weight for leg in ordered), Decimal(0))
    if total == 0:
        raise ValidationError("腿权重全为 0, 无法归一化到 1")
    return tuple(replace(leg, target_weight=leg.target_weight / total) for leg in ordered)


def build_target(
    legs: Iterable[TargetLeg],
    constraints: PortfolioConstraints,
    *,
    as_of: datetime,
) -> TargetPortfolio:
    """把调用方给出的腿与权重变成一份满足约束、权重绝对值之和为 1 的目标组合。

    约束分两阶段检查，两阶段判的不是同一组边界：

    - 请求的权重先过四项上限：策略超额请求（例如两腿各 0.6 而单标的上限 0.5）必须
      被拒绝，缩放只会把权重变小，不能靠缩放把超额请求洗成合规；
    - 归一化后再判全部五项：总权重不足 1 时归一化会放大权重，放大后的每条腿才
      真正代表持有的比例，单腿权重下限只在这一步判——两腿各 0.2 归一化后是 0.5 与
      0.5，在请求阶段按 0.2 判下限会把合法输入误拒。
    """

    requested = _legs(legs)
    check_upper_bounds(requested, constraints)
    normalized = normalize_weights(requested)
    check_constraints(normalized, constraints)
    return TargetPortfolio(as_of=as_of, legs=normalized)


def target_quantity(
    leg: TargetLeg,
    instrument: InstrumentRef,
    *,
    price: Decimal,
    capital: Decimal,
) -> TargetQuantity:
    """把一条腿的目标权重换成本次可以下的数量。

    走哪条公式由 `trading_rules(inst_type).qty_unit` 决定，这里不判断类别：

    - `contract`（永续）：`weight * capital / (price * ct_val)`，再按 `lot_size` 向下取整；
    - `base`（现货）：`weight * capital / price`，再按 `lot_size` 向下取整，不经过 `ct_val`。

    未知的单位直接报错，而不是回落到现货公式：新增类别时宁可炸在这里，也不要静默算
    出一个小了几个数量级的数量。
    """

    _require_positive(price, "price")
    _require_positive(capital, "capital")
    lot_size = instrument.lot_size
    if lot_size is None:
        raise ValidationError(f"标的 {instrument.inst_id} 缺少 lot_size, 无法换算下单数量")
    _require_positive(lot_size, "lot_size")

    unit = trading_rules(instrument.inst_type).qty_unit
    notional = leg.target_weight * capital
    if unit == _UNIT_CONTRACT:
        ct_val = instrument.ct_val
        if ct_val is None:
            raise ValidationError(f"标的 {instrument.inst_id} 缺少 ct_val, 无法换算合约张数")
        _require_positive(ct_val, "ct_val")
        theoretical = notional / (price * ct_val)
    elif unit == _UNIT_BASE:
        theoretical = notional / price
    else:  # 现有类别只声明这两种单位；新增单位必须在这里补公式，不能沿用现货的
        raise ValidationError(f"标的 {instrument.inst_id} 的数量单位 {unit!r} 没有换算公式")

    steps = (theoretical / lot_size).to_integral_value(rounding=ROUND_FLOOR)
    qty = steps * lot_size
    return TargetQuantity(
        inst_id=instrument.inst_id,
        qty=qty,
        unit=unit,
        discarded=theoretical - qty,
    )


def _require_positive(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal):
        raise ValidationError(f"{name} 必须是 Decimal, 实际 {type(value).__name__}")
    if not value.is_finite() or value <= 0:
        raise ValidationError(f"{name} 必须是正有限数, 实际 {value}")

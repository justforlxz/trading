"""跨策略的一致性检查与全局敞口（纯函数，无 IO）。

三件事各自只有一个实现：

1. **重复持仓与多空冲突**：同一 `product_key` 上，两个及以上策略方向相反时返回一条
   冲突，两侧策略标识都列出、不合并成一句「有冲突」。
2. **单策略敞口**：一个策略的持仓权重（名义价值 ÷ 该策略资金预算）之和。多头为正、
   空头为负；总敞口取绝对值之和。
3. **全局敞口**：各策略权重逐条累加，因此「净敞口 = 多头权重之和 − 空头权重之和」
   是一条恒等式，而不是另算一遍再去对账。集中度取单一产品净名义价值绝对值的最大值
   除以各策略资金预算之和；各策略预算不同时，权重不能直接跨策略相加当集中度用。

权重是比率，不是金额：单策略权重以该策略自己的预算为分母，全局净敞口因此是各策略
权重的直接相加（验收原文的口径）。金额口径的盈亏与名义价值由调用方单独保留。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from app.core import ValidationError

__all__ = [
    "ExposureAggregate",
    "ExposureLeg",
    "PortfolioConflict",
    "aggregate_exposure",
    "net_exposure",
    "product_conflicts",
]

SIDE_LONG = "long"
SIDE_SHORT = "short"
ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class ExposureLeg:
    """一条参与敞口汇总的持仓：哪个策略、哪个产品、方向、权重与名义价值。"""

    instance_id: str
    product_key: str
    direction: str
    weight: Decimal
    notional: Decimal

    def __post_init__(self) -> None:
        if not self.instance_id.strip():
            raise ValidationError("敞口必须给出策略实例")
        if not self.product_key.strip():
            raise ValidationError("敞口必须给出产品键")
        if self.direction not in {SIDE_LONG, SIDE_SHORT}:
            raise ValidationError(f"敞口方向必须是 long / short, 实际 {self.direction!r}")
        if not isinstance(self.weight, Decimal) or not self.weight.is_finite():
            raise ValidationError(f"敞口权重必须是有限 Decimal, 实际 {self.weight!r}")
        if not isinstance(self.notional, Decimal) or not self.notional.is_finite():
            raise ValidationError(f"敞口名义价值必须是有限 Decimal, 实际 {self.notional!r}")
        if self.notional < ZERO:
            raise ValidationError(f"敞口名义价值不能为负, 实际 {self.notional}")

    @property
    def signed_weight(self) -> Decimal:
        return self.weight if self.direction == SIDE_LONG else -self.weight


@dataclass(frozen=True, slots=True)
class PortfolioConflict:
    """同一产品上的多空冲突；两侧策略标识都已排序，便于直接比较。"""

    product_key: str
    long_instance_ids: tuple[str, ...]
    short_instance_ids: tuple[str, ...]


def product_conflicts(legs: Iterable[ExposureLeg]) -> tuple[PortfolioConflict, ...]:
    """找出方向相反的产品；同一产品需要至少一个多头与一个空头才算冲突。

    同一方向上的多个策略是重复持仓，不是冲突：它们不在这里返回，也不被悄悄合并。
    """

    long_by_product: dict[str, set[str]] = {}
    short_by_product: dict[str, set[str]] = {}
    for leg in legs:
        target = long_by_product if leg.direction == SIDE_LONG else short_by_product
        target.setdefault(leg.product_key, set()).add(leg.instance_id)

    conflicts: list[PortfolioConflict] = []
    for product_key in sorted(long_by_product.keys() & short_by_product.keys()):
        conflicts.append(
            PortfolioConflict(
                product_key=product_key,
                long_instance_ids=tuple(sorted(long_by_product[product_key])),
                short_instance_ids=tuple(sorted(short_by_product[product_key])),
            )
        )
    return tuple(conflicts)


def net_exposure(weights: Iterable[tuple[str, Decimal]]) -> Decimal:
    """多头权重之和减空头权重之和；输入是（方向，权重）序列。"""

    total = ZERO
    for direction, weight in weights:
        if direction not in {SIDE_LONG, SIDE_SHORT}:
            raise ValidationError(f"敞口方向必须是 long / short, 实际 {direction!r}")
        total += weight if direction == SIDE_LONG else -weight
    return total


@dataclass(frozen=True, slots=True)
class ExposureAggregate:
    """一次汇总的结果：四项敞口比率、单一产品最大占比、持仓与产品计数。"""

    gross_exposure: Decimal
    net_exposure: Decimal
    long_exposure: Decimal
    short_exposure: Decimal
    largest_position_share: Decimal
    open_positions: int
    product_count: int
    conflicts: tuple[PortfolioConflict, ...]


def aggregate_exposure(legs: Iterable[ExposureLeg], *, equity: Decimal) -> ExposureAggregate:
    """按权重汇总全局敞口。

    `legs` 里每条腿的权重 = 名义价值 ÷ 该策略预算，由调用方先算好（纯函数不读配置）。
    这里把权重直接逐条相加：`net = long − short` 由同一组加法得到，不存在第二个来源。

    `largest_position_share` 取单一产品净名义价值绝对值的最大值除以组合权益
    （`equity`，各策略资金预算之和）。权重仍按各策略自己的预算折算，用于验收要求的
    净敞口等式；集中度统一用金额和同一个权益分母，避免不同预算的权重跨策略相加。
    """

    legs = tuple(legs)
    if not isinstance(equity, Decimal) or not equity.is_finite() or equity < ZERO:
        raise ValidationError(f"组合权益必须是非负有限 Decimal, 实际 {equity!r}")
    long_weight = ZERO
    short_weight = ZERO
    by_product_weight: dict[str, Decimal] = {}
    by_product_notional: dict[str, Decimal] = {}
    for leg in legs:
        if leg.direction == SIDE_LONG:
            long_weight += leg.weight
        else:
            short_weight += leg.weight
        by_product_weight[leg.product_key] = (
            by_product_weight.get(leg.product_key, ZERO) + leg.signed_weight
        )
        signed_notional = leg.notional if leg.direction == SIDE_LONG else -leg.notional
        by_product_notional[leg.product_key] = (
            by_product_notional.get(leg.product_key, ZERO) + signed_notional
        )

    largest_notional = max((abs(value) for value in by_product_notional.values()), default=ZERO)
    largest = largest_notional / equity if equity > ZERO else ZERO
    return ExposureAggregate(
        gross_exposure=long_weight + short_weight,
        net_exposure=net_exposure((leg.direction, leg.weight) for leg in legs),
        long_exposure=long_weight,
        short_exposure=short_weight,
        largest_position_share=largest,
        open_positions=len(legs),
        product_count=len(by_product_weight),
        conflicts=product_conflicts(legs),
    )

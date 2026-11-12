"""逐仓保证金、杠杆档位与强平价（纯函数）。

永续的杠杆与保证金口径来自 OKX `position-tiers`：一个 `instFamily` 一份档位表，按
持仓规模落档，取该档的 `maxLever` 与 `mmr`。现货没有杠杆、没有保证金占用、也不会
被强平——这三种差异由标的模块的 `trading_rules(inst_type).has_margin` 表达，本模块
不写类别分支：`margin_terms` 对没有保证金的类别直接给出「杠杆 1、占用 0、无强平价」。

## 强平公式

逐仓、单腿、不计手续费与资金费，强平距（强平价到开仓价的距离）用这个简化式：

    强平距 = avgPx × (1/lever − mmr)
    多仓 liqPx = avgPx − 强平距
    空仓 liqPx = avgPx + 强平距

精确式是「权益 = 按强平价计算的维持保证金」那一刻：多仓
`liqPx = avgPx × (1 − 1/lever) / (1 − mmr)`，对应距离 `avgPx × (1/lever − mmr) / (1 − mmr)`。
两者只差 `(1 − mmr)` 倍（简化式距离 = 精确式距离 × `(1 − mmr)`），因此简化式的强平距
更短、更早判强平，方向偏保守。与交易所 `liqPx` 的一致性以对账为准，不宣称公式精确
（D1 实施约束）。

两侧距离相同，因此多空镜像相等；`mmr` 越大距离越小，`lever` 越大占用保证金越少、
距离也越小。当 `1/lever ≤ mmr` 时距离不为正（简化式会把强平价放到开仓价的错误
一侧），`liquidation_price` 直接报 `ValidationError` 而不是返回一个假价位；现有 87 档
里 `effective_leverage` 被硬上限 10 与各档 `maxLever` 压住，正常数据不会走到这一步。

bar 内判定只回答「这根 K 线的价格区间是否触及强平价」，跳空时直接按强平价结算，
不模拟更差的成交价。

## 杠杆上限

可用杠杆取 `min(settings.max_leverage, 该档 maxLever, 10)`。硬上限 10 写在本模块：
配置把 `max_leverage` 调高也不会突破它（L1 资金安全四件套）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.backtest.simulation import LONG, SIDES, require_positive
from app.core import UpstreamError, ValidationError
from app.instrument import trading_rules

__all__ = [
    "DEFAULT_MAX_LEVERAGE",
    "HARD_MAX_LEVERAGE",
    "MarginTerms",
    "PositionTier",
    "effective_leverage",
    "initial_margin",
    "liquidated_in_bar",
    "liquidation_price",
    "maintenance_margin",
    "margin_terms",
    "margin_used",
    "max_loss",
    "parse_position_tiers",
    "tier_for",
]

ONE = Decimal(1)
ZERO = Decimal(0)

#: 本地杠杆默认值与硬上限（D1 / L1）；硬上限不由配置抬高。
DEFAULT_MAX_LEVERAGE = Decimal(3)
HARD_MAX_LEVERAGE = Decimal(10)


@dataclass(frozen=True, slots=True)
class PositionTier:
    """`position-tiers` 的一档：覆盖的持仓规模区间、该档杠杆上限与维持保证金率。

    `size_min` / `size_max` 用上游的持仓规模单位（USDT 本位永续为张数），本模块不
    做单位换算：落档与计息用的是同一个量，换算是交易所适配层的职责。
    """

    size_min: Decimal
    size_max: Decimal
    max_leverage: Decimal
    maintenance_margin_rate: Decimal

    def covers(self, size: Decimal) -> bool:
        """这一档是否覆盖该持仓规模（闭区间，与上游 `minSz`/`maxSz` 一致）。"""

        return self.size_min <= size <= self.size_max


@dataclass(frozen=True, slots=True)
class MarginTerms:
    """一个类别、一条腿的杠杆与保证金口径。

    `has_margin` 为假时（现货）其余字段的含义固定：`leverage` 恒为 1、`tier` 与
    `liquidation_price` 都是 `None`——现货既不占用保证金，也没有强平价。
    """

    has_margin: bool
    leverage: Decimal
    tier: PositionTier | None
    liquidation_price: Decimal | None


def parse_position_tiers(rows: Iterable[Mapping[str, Any]]) -> tuple[PositionTier, ...]:
    """上游档位表 → 按持仓规模升序的档位序列；结构或取值不合规一律按上游故障上抛。

    纯函数：不发请求、不落库。档位表只做「能读懂」的校验（区间合法、杠杆不小于 1、
    `mmr` 落在 0 与 1 之间），是否连续留给上游：上游若给了缺口，`tier_for` 会在缺口
    里的规模上报错，而不是悄悄借用相邻档。
    """

    tiers: list[PositionTier] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise UpstreamError(f"档位数据结构异常:{row!r}")
        tier = PositionTier(
            size_min=_decimal(row, "minSz"),
            size_max=_decimal(row, "maxSz"),
            max_leverage=_decimal(row, "maxLever"),
            maintenance_margin_rate=_decimal(row, "mmr"),
        )
        if tier.size_min < ZERO or tier.size_max <= tier.size_min:
            raise UpstreamError(f"档位规模区间非法:{row!r}")
        if tier.max_leverage < ONE:
            raise UpstreamError(f"档位杠杆上限非法:{row!r}")
        if not ZERO <= tier.maintenance_margin_rate < ONE:
            raise UpstreamError(f"档位维持保证金率非法:{row!r}")
        tiers.append(tier)
    if not tiers:
        raise UpstreamError("档位表为空")
    tiers.sort(key=lambda item: item.size_min)
    return tuple(tiers)


def tier_for(tiers: Sequence[PositionTier], size: Decimal) -> PositionTier:
    """持仓规模落在哪一档；超出全部档位或落在缺口里都报错，不退到相邻档。"""

    wanted = require_positive(size, "持仓规模")
    for tier in tiers:
        if tier.covers(wanted):
            return tier
    raise ValidationError(f"持仓规模 {wanted} 不在 {len(tiers)} 档位表的覆盖范围内")


def effective_leverage(
    max_leverage: Decimal,
    tiers: Sequence[PositionTier],
    size: Decimal,
) -> Decimal:
    """可用杠杆 = min(本地上限, 该档杠杆上限, 硬上限 10)。"""

    cap = min(_require_leverage(max_leverage, "max_leverage"), HARD_MAX_LEVERAGE)
    return min(cap, tier_for(tiers, size).max_leverage)


def initial_margin(notional: Decimal, leverage: Decimal) -> Decimal:
    """逐仓开仓占用的初始保证金 = 名义金额 / 杠杆。"""

    amount = require_positive(notional, "名义金额")
    return amount / _require_leverage(leverage, "leverage")


def maintenance_margin(notional: Decimal, maintenance_margin_rate: Decimal) -> Decimal:
    """维持保证金 = 名义金额 × 维持保证金率。"""

    amount = require_positive(notional, "名义金额")
    return amount * _require_mmr(maintenance_margin_rate)


def liquidation_price(
    *,
    side: str,
    entry_price: Decimal,
    leverage: Decimal,
    maintenance_margin_rate: Decimal,
) -> Decimal:
    """逐仓强平价，用简化式 `强平距 = avgPx × (1/lever − mmr)`：多仓减、空仓加。

    简化式的距离是精确式（权益 = 按强平价扣的维持保证金）的 `(1 − mmr)` 倍，因此更早
    判强平、方向偏保守。`1/lever ≤ mmr` 时距离不为正，这里直接报错而不是给假价位。

    算出来的价位不高于 0 时同样报错，不返回 0 或负数：`1/杠杆 − mmr == 1`（杠杆 1 且
    `mmr` 为 0）的多仓就会落到 0，而 0 不是可成交的价格——`liquidated_in_bar` 按
    「强平价必须是正数」校验，放它过去会让两个函数对同一份数据给出相反的回答。
    """

    _require_side(side)
    entry = require_positive(entry_price, "开仓价")
    leverage_used = _require_leverage(leverage, "leverage")
    mmr = _require_mmr(maintenance_margin_rate)
    distance = ONE / leverage_used - mmr
    if distance <= ZERO:
        raise ValidationError(
            f"杠杆 {leverage} 下 1/杠杆 不大于维持保证金率 {maintenance_margin_rate},"
            "该组合没有强平价"
        )
    offset = entry * distance
    level = entry - offset if side == LONG else entry + offset
    if level <= ZERO:
        raise ValidationError(
            f"开仓价 {entry} 在杠杆 {leverage_used} 与维持保证金率 {mmr} 下的强平价是 {level},"
            "不高于 0: 该组合没有可触及的强平价"
        )
    return level


def liquidated_in_bar(
    *,
    side: str,
    liquidation_price: Decimal,
    high: Decimal,
    low: Decimal,
) -> bool:
    """这根 K 线的价格区间是否触及强平价；多仓看最低价，空仓看最高价。"""

    _require_side(side)
    level = require_positive(liquidation_price, "强平价")
    top = require_positive(high, "最高价")
    bottom = require_positive(low, "最低价")
    if top < bottom:
        raise ValidationError(f"K 线的最高价 {top} 低于最低价 {bottom}")
    if side == LONG:
        return bottom <= level
    return top >= level


def margin_terms(
    *,
    inst_type: str,
    side: str,
    entry_price: Decimal,
    size: Decimal,
    max_leverage: Decimal = DEFAULT_MAX_LEVERAGE,
    tiers: Sequence[PositionTier] = (),
) -> MarginTerms:
    """本类别、本腿的杠杆与保证金口径；类别差异只查 `trading_rules`，不写类别分支。

    方向、开仓价、持仓规模三类入参在**分类别之前**校验：它们对现货与永续是同一个含义，
    放在类别分支之后会让同一组非法参数在现货上被放过、在永续上被拒绝。
    """

    _require_side(side)
    require_positive(entry_price, "开仓价")
    require_positive(size, "持仓规模")

    if not trading_rules(inst_type).has_margin:
        return MarginTerms(
            has_margin=False,
            leverage=ONE,
            tier=None,
            liquidation_price=None,
        )

    tier = tier_for(tiers, size)
    leverage = effective_leverage(max_leverage, tiers, size)
    return MarginTerms(
        has_margin=True,
        leverage=leverage,
        tier=tier,
        liquidation_price=liquidation_price(
            side=side,
            entry_price=entry_price,
            leverage=leverage,
            maintenance_margin_rate=tier.maintenance_margin_rate,
        ),
    )


def margin_used(terms: MarginTerms, notional: Decimal) -> Decimal:
    """这条腿占用的保证金；没有保证金的类别恒为 0。"""

    if not terms.has_margin:
        return ZERO
    return initial_margin(notional, terms.leverage)


def max_loss(
    terms: MarginTerms,
    *,
    side: str,
    notional: Decimal,
) -> Decimal | None:
    """这条腿的最大亏损上限。

    有保证金的类别逐仓结算，价格再走也只会亏掉占用的保证金；没有保证金的类别多头
    以买入金额为上限（价格跌到 0 为止），空头的理论亏损没有上限，因此返回 `None`。
    """

    _require_side(side)
    amount = require_positive(notional, "名义金额")
    if terms.has_margin:
        return initial_margin(amount, terms.leverage)
    if side == LONG:
        return amount
    return None


def _decimal(row: Mapping[str, Any], field: str) -> Decimal:
    """档位行的一个数值字段 → `Decimal`；空值或非法文本按上游故障处理。"""

    raw = row.get(field)
    if raw is None or raw == "":
        raise UpstreamError(f"档位缺少 {field}:{row!r}")
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise UpstreamError(f"档位 {field} 非法:{row!r}") from exc


def _require_side(side: str) -> str:
    if side not in SIDES:
        raise ValidationError(f"方向必须是 {sorted(SIDES)}, 实际 {side!r}")
    return side


def _require_leverage(value: Decimal, name: str) -> Decimal:
    """杠杆必须是有限数且不小于 1；小于 1 的「杠杆」等于自带保证金，不是本模型的输入。"""

    if not isinstance(value, Decimal):
        raise ValidationError(f"{name} 必须是 Decimal, 实际 {type(value).__name__}")
    if not value.is_finite() or value < ONE:
        raise ValidationError(f"{name} 必须是有限数且不小于 1, 实际 {value}")
    return value


def _require_mmr(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal):
        raise ValidationError(f"维持保证金率必须是 Decimal, 实际 {type(value).__name__}")
    if not value.is_finite() or not ZERO <= value < ONE:
        raise ValidationError(f"维持保证金率必须在 0 与 1 之间, 实际 {value}")
    return value

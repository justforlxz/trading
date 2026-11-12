"""策略级虚拟持仓的 FIFO 成本核算（纯函数，无 IO）。

## 为什么是先进先出

一笔卖出先冲掉最早买入的那一批，剩下的成本价仍是后面那批的价格。用移动平均会把
「先买的便宜、后买的贵」摊成一笔平均值，已实现盈亏与剩余成本同时失真。验收的已知
答案就建立在这个口径上：买 1 张 @100、再买 1 张 @110、卖 1 张 @120，已实现盈亏 20，
剩余成本价 110。

## 手续费

手续费在成交时全额计入已实现盈亏（现金支出），不摊到每一批的成本里。另用 `fees`
累计费用总额，便于单独查看。这样「已实现盈亏 + 未实现盈亏 − 手续费」的关系不需要
靠另一个字段再补一次。

## 合约面值

`qty` 对永续合约是张数，不是标的数量。价差必须再乘合约面值（`ct_val`）才是报价币
盈亏；调用方把该乘数显式传给 `apply_fill` 与 `unrealized_pnl`，现货传 1。账本不
自行猜测标的类别，数量口径因此始终保持「交易所数量」。

## 数量与方向

`Lot.qty` 恒为正数，方向由 `LedgerPosition.direction` 表达（`long` / `short`，
没有持仓时为 `None`）。反向成交先把当前持仓按 FIFO 冲掉；冲过头时剩余数量按成交价
开成反方向的新持仓（净头寸翻转），这与真实交易里「卖超后变成空头」是同一件事。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from app.core import ValidationError

__all__ = [
    "BUY",
    "SELL",
    "LedgerPosition",
    "Lot",
    "apply_fill",
    "unrealized_pnl",
]

SIDE_LONG = "long"
SIDE_SHORT = "short"
BUY = "buy"
SELL = "sell"
ONE = Decimal(1)

_SIDES = frozenset({BUY, SELL})
DIRECTIONS = frozenset({SIDE_LONG, SIDE_SHORT})
ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class Lot:
    """一批同价买入/卖出的持仓；`qty` 为正，`price` 是该批的成交价。"""

    qty: Decimal
    price: Decimal

    def __post_init__(self) -> None:
        _require_positive(self.qty, "批次数量")
        _require_positive(self.price, "批次价格")


@dataclass(frozen=True, slots=True)
class LedgerPosition:
    """一个策略在一个标的上的账本状态；`lots` 为空表示当前没有持仓。"""

    direction: str | None
    lots: tuple[Lot, ...]
    realized_pnl: Decimal = ZERO
    fees: Decimal = ZERO

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS and self.direction is not None:
            raise ValidationError(f"持仓方向必须是 long / short / None, 实际 {self.direction!r}")
        if self.direction is None and self.lots:
            raise ValidationError("没有持仓方向时不能带批次")
        if self.direction is not None and not self.lots:
            raise ValidationError("有持仓方向时必须至少有一批持仓")

    @property
    def qty(self) -> Decimal:
        """当前持仓数量（正数）；没有持仓时为 0。"""

        return sum((lot.qty for lot in self.lots), ZERO)

    @property
    def avg_cost(self) -> Decimal:
        """剩余批次的加权平均成本；没有持仓时为 0。"""

        qty = self.qty
        if qty == ZERO:
            return ZERO
        return sum((lot.qty * lot.price for lot in self.lots), ZERO) / qty


def apply_fill(
    position: LedgerPosition,
    *,
    side: str,
    qty: Decimal,
    price: Decimal,
    fee: Decimal = ZERO,
    multiplier: Decimal = ONE,
) -> LedgerPosition:
    """把一笔成交记进账本，返回新的状态（不修改入参）。

    - 方向相同或当前空仓：追加一批，方向取「买入为多、卖出为空」；
    - 方向相反：按 FIFO 冲掉最早批次，差额按成交价开反方向新仓；
    - 手续费从已实现盈亏里扣（见模块文档），`fees` 同步累计；
    - `multiplier` 是合约面值，价差先乘它再计入盈亏；现货与未平仓数量不缩放。
    """

    if side not in _SIDES:
        raise ValidationError(f"成交方向必须是 {sorted(_SIDES)}, 实际 {side!r}")
    _require_positive(qty, "成交数量")
    _require_positive(price, "成交价格")
    _require_positive(multiplier, "合约面值")
    if not isinstance(fee, Decimal) or not fee.is_finite() or fee < ZERO:
        raise ValidationError(f"手续费必须是非负有限数, 实际 {fee!r}")

    fees = position.fees + fee
    if position.direction is None:
        return LedgerPosition(
            direction=SIDE_LONG if side == BUY else SIDE_SHORT,
            lots=(Lot(qty, price),),
            realized_pnl=position.realized_pnl - fee,
            fees=fees,
        )

    opening_side = BUY if position.direction == SIDE_LONG else SELL
    if side == opening_side:
        return replace(
            position,
            lots=(*position.lots, Lot(qty, price)),
            realized_pnl=position.realized_pnl - fee,
            fees=fees,
        )

    remaining = qty
    realized = position.realized_pnl
    lots: list[Lot] = []
    for lot in position.lots:
        if remaining == ZERO:
            lots.append(lot)
            continue
        take = min(lot.qty, remaining)
        if position.direction == SIDE_LONG:
            realized += (price - lot.price) * take * multiplier
        else:
            realized += (lot.price - price) * take * multiplier
        remaining -= take
        left = lot.qty - take
        if left > ZERO:
            lots.append(Lot(left, lot.price))

    if remaining > ZERO:
        # 冲过头：剩余数量按成交价开反方向新仓，方向由这笔成交决定。
        flipped = SIDE_SHORT if position.direction == SIDE_LONG else SIDE_LONG
        return LedgerPosition(
            direction=flipped,
            lots=(Lot(remaining, price),),
            realized_pnl=realized - fee,
            fees=fees,
        )

    if not lots:
        return LedgerPosition(
            direction=None,
            lots=(),
            realized_pnl=realized - fee,
            fees=fees,
        )
    return LedgerPosition(
        direction=position.direction,
        lots=tuple(lots),
        realized_pnl=realized - fee,
        fees=fees,
    )


def unrealized_pnl(
    position: LedgerPosition,
    mark_price: Decimal,
    multiplier: Decimal = ONE,
) -> Decimal:
    """按给定标记价算未实现盈亏；没有持仓时为 0。

    `multiplier` 是合约面值：永续合约的数量是张数，价差要乘面值才是报价币金额。
    """

    if mark_price < ZERO or not mark_price.is_finite():
        raise ValidationError(f"标记价必须是非负有限数, 实际 {mark_price!r}")
    _require_positive(multiplier, "合约面值")
    qty = position.qty
    if position.direction is None or qty == ZERO:
        return ZERO
    if position.direction == SIDE_LONG:
        return (mark_price - position.avg_cost) * qty * multiplier
    return (position.avg_cost - mark_price) * qty * multiplier


def _require_positive(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal):
        raise ValidationError(f"{name} 必须是 Decimal, 实际 {type(value).__name__}")
    if not value.is_finite() or value <= ZERO:
        raise ValidationError(f"{name} 必须是正有限数, 实际 {value}")

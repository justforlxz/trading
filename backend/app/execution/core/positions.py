"""策略级虚拟持仓与收益归因（纯函数）。

一个持仓 = `(strategy, instrument, position_side)` 上的非负数量 + 均价 + 已实现盈亏。
开/平仓由 `position_side` 与成交 `side` 共同决定：

    long  + buy  = 开仓/加仓      long  + sell = 平仓/减仓
    short + sell = 开仓/加仓      short + buy  = 平仓/减仓

P3 不做反向翻仓：平仓数量超过持仓直接报错，翻仓必须拆成「平仓 + 开仓」两笔。
手续费直接冲减已实现盈亏，不进入均价。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal("0")

POSITION_SIDES = ("long", "short")
OPENING_SIDES = {"long": "buy", "short": "sell"}


class PositionError(ValueError):
    """持仓数学错误（越界平仓、非法方向等）。"""

    code = "execution_position_error"


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    position_side: str
    quantity: Decimal
    average_price: Decimal
    realized_pnl: Decimal


EMPTY_LONG = PositionSnapshot("long", ZERO, ZERO, ZERO)
EMPTY_SHORT = PositionSnapshot("short", ZERO, ZERO, ZERO)


def empty(position_side: str) -> PositionSnapshot:
    if position_side not in POSITION_SIDES:
        raise PositionError(f"unknown position_side: {position_side}")
    return EMPTY_LONG if position_side == "long" else EMPTY_SHORT


def is_opening(position_side: str, side: str) -> bool:
    """成交是开仓（True）还是平仓（False）。"""

    if position_side not in POSITION_SIDES:
        raise PositionError(f"unknown position_side: {position_side}")
    if side not in {"buy", "sell"}:
        raise PositionError(f"unknown side: {side}")
    return OPENING_SIDES[position_side] == side


def apply_fill(
    position: PositionSnapshot,
    *,
    side: str,
    quantity: Decimal,
    price: Decimal,
    fee: Decimal = ZERO,
) -> PositionSnapshot:
    """把一笔成交作用到持仓上，返回新持仓（纯函数）。"""

    if quantity <= ZERO:
        raise PositionError("成交数量必须为正")
    if price <= ZERO:
        raise PositionError("成交价格必须为正")

    if is_opening(position.position_side, side):
        total = position.quantity + quantity
        notional = position.average_price * position.quantity + price * quantity
        return PositionSnapshot(
            position_side=position.position_side,
            quantity=total,
            average_price=notional / total,
            realized_pnl=position.realized_pnl - fee,
        )

    if quantity > position.quantity:
        raise PositionError(f"平仓数量 {quantity} 超过持仓 {position.quantity} (P3 不支持反向翻仓)")
    if position.position_side == "long":
        pnl = (price - position.average_price) * quantity
    else:
        pnl = (position.average_price - price) * quantity
    remaining = position.quantity - quantity
    return PositionSnapshot(
        position_side=position.position_side,
        quantity=remaining,
        average_price=position.average_price if remaining > ZERO else ZERO,
        realized_pnl=position.realized_pnl + pnl - fee,
    )


@dataclass(frozen=True, slots=True)
class PositionValuation:
    """带标记价格的持仓估值；用于账户汇总与止损判断。"""

    strategy_id: int | None
    instrument_id: int
    inst_id: str
    position_side: str
    quantity: Decimal
    average_price: Decimal
    realized_pnl: Decimal
    mark_price: Decimal | None

    @property
    def unrealized_pnl(self) -> Decimal | None:
        if self.mark_price is None or self.quantity == ZERO:
            return None
        if self.position_side == "long":
            return (self.mark_price - self.average_price) * self.quantity
        return (self.average_price - self.mark_price) * self.quantity

    @property
    def notional(self) -> Decimal:
        price = self.mark_price if self.mark_price is not None else self.average_price
        return price * self.quantity


@dataclass(frozen=True, slots=True)
class PositionRow:
    """与 ORM 解耦的持仓输入行。"""

    strategy_id: int | None
    instrument_id: int
    inst_id: str
    position_side: str
    quantity: Decimal
    average_price: Decimal
    realized_pnl: Decimal


def mark_to_market(
    rows: tuple[PositionRow, ...] | list[PositionRow],
    marks: Mapping[tuple[int, str], Decimal],
) -> list[PositionValuation]:
    """按 `(instrument_id, position_side)` 的标记价格给持仓估值。"""

    valuations: list[PositionValuation] = []
    for row in rows:
        valuations.append(
            PositionValuation(
                strategy_id=row.strategy_id,
                instrument_id=row.instrument_id,
                inst_id=row.inst_id,
                position_side=row.position_side,
                quantity=row.quantity,
                average_price=row.average_price,
                realized_pnl=row.realized_pnl,
                mark_price=marks.get((row.instrument_id, row.position_side)),
            )
        )
    return valuations


@dataclass(frozen=True, slots=True)
class AccountTotals:
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    gross_notional: Decimal
    net_notional: Decimal
    positions: int

    @property
    def total_pnl(self) -> Decimal:
        return self.realized_pnl + self.unrealized_pnl


def account_totals(valuations: list[PositionValuation]) -> AccountTotals:
    """账户合计：逐策略估值求和，是「策略级归属之和 = 账户」的落点。"""

    realized = ZERO
    unrealized = ZERO
    gross = ZERO
    net = ZERO
    for item in valuations:
        realized += item.realized_pnl
        unrealized += item.unrealized_pnl or ZERO
        gross += item.notional
        net += item.notional if item.position_side == "long" else -item.notional
    return AccountTotals(
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        gross_notional=gross,
        net_notional=net,
        positions=len(valuations),
    )


def unrealized_ratio(valuation: PositionValuation) -> Decimal | None:
    """浮盈浮亏占持仓均价的比例；无标记价格或空仓返回 None。"""

    pnl = valuation.unrealized_pnl
    if pnl is None or valuation.average_price <= ZERO:
        return None
    return pnl / (valuation.average_price * valuation.quantity)


__all__ = [
    "OPENING_SIDES",
    "POSITION_SIDES",
    "AccountTotals",
    "PositionError",
    "PositionRow",
    "PositionSnapshot",
    "PositionValuation",
    "account_totals",
    "apply_fill",
    "empty",
    "is_opening",
    "mark_to_market",
    "unrealized_ratio",
]

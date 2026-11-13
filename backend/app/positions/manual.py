"""手动持仓账本的纯函数：加权成本、部分卖出、清仓与流水回放。

本模块不碰数据库、不发 HTTP，输入输出都是 `Decimal` 与 `datetime`，可以直接用
已知答案断言。服务层只负责事务边界与落库。

## 口径

- 买入、加仓、开仓：`new_qty = qty + q`，
  `new_cost = (qty * avg_cost + q * price + fee) / new_qty`。
- 卖出、减仓：数量相减，`avg_cost` 不变；已实现盈亏按持仓方向计算：多头
  `(price - avg_cost) * q - fee`，空头 `(avg_cost - price) * q - fee`。
- 清仓：数量必须等于当前数量，状态改为 `closed`。
- 更正：把数量与平均成本直接改成流水给出的值；这是账本更正，不产生已实现盈亏，
  因此不接受手续费。

数量超过当前持仓、清仓数量不符都属于「参数合法但当前状态不允许」，抛
`UnprocessableEntity`（HTTP 422）。数量、价格、费用本身不合法则抛
`ValidationError`（HTTP 400）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.core import InvariantViolation, UnprocessableEntity, ValidationError

__all__ = [
    "MANUAL_ACTIONS",
    "LedgerTrade",
    "TradeEffect",
    "TradeProjection",
    "apply_trade",
    "replay_trades",
]

MANUAL_ACTIONS = frozenset({"open", "add", "reduce", "close", "correct"})
_SIDE_EFFECTS = frozenset({"open", "add", "reduce", "close", "correct"})
LONG = "long"
SHORT = "short"
_SIDES = frozenset({LONG, SHORT})
OPEN = "open"
CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class TradeEffect:
    """一笔流水对持仓的结果。"""

    quantity: Decimal
    avg_cost: Decimal
    status: str
    realized_pnl: Decimal | None


@dataclass(frozen=True, slots=True)
class LedgerTrade:
    """回放流水所需的最小事实集合。"""

    trade_id: str
    action: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    occurred_at: datetime
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TradeProjection:
    """一条流水及其发生后的持仓状态。"""

    trade: LedgerTrade
    quantity_after: Decimal
    avg_cost_after: Decimal
    status_after: str
    realized_pnl: Decimal | None


def apply_trade(
    *,
    action: str,
    side: str,
    current_quantity: Decimal,
    current_avg_cost: Decimal,
    quantity: Decimal,
    price: Decimal,
    fee: Decimal = Decimal(0),
) -> TradeEffect:
    """按动作把一笔流水应用到当前持仓状态。

    `side` 是持仓方向，决定减仓与清仓的已实现盈亏符号：多头在价格上涨时盈利，
    空头在价格下跌时盈利。它与 `_manual_position_view` 里未实现盈亏的方向口径一致。
    """

    _require_ledger_inputs(
        action=action,
        side=side,
        current_quantity=current_quantity,
        current_avg_cost=current_avg_cost,
        quantity=quantity,
        price=price,
        fee=fee,
    )

    if action in {"open", "add"}:
        new_quantity = current_quantity + quantity
        new_cost = (current_quantity * current_avg_cost + quantity * price + fee) / new_quantity
        return TradeEffect(new_quantity, new_cost, OPEN, None)

    if action == "correct":
        if fee != 0:
            raise ValidationError("更正流水不接受手续费")
        return TradeEffect(quantity, price, OPEN, None)

    if action in {"reduce", "close"}:
        if quantity > current_quantity:
            raise UnprocessableEntity(f"数量 {quantity} 超过当前持仓 {current_quantity}")
        if quantity <= 0:
            raise ValidationError("数量必须大于 0")
        if action == "close" and quantity != current_quantity:
            raise UnprocessableEntity(
                f"清仓数量必须等于当前持仓 {current_quantity}, 实际 {quantity}"
            )
        new_quantity = current_quantity - quantity
        if side == LONG:
            realized = (price - current_avg_cost) * quantity - fee
        else:
            realized = (current_avg_cost - price) * quantity - fee
        status = CLOSED if new_quantity == 0 else OPEN
        return TradeEffect(new_quantity, current_avg_cost, status, realized)

    raise ValidationError(f"不支持的手动持仓动作 {action!r}")


def replay_trades(trades: list[LedgerTrade], *, side: str) -> list[TradeProjection]:
    """按发生时刻重放流水，返回每条流水之后的持仓数量、成本与状态。

    同一时刻的流水按写入时刻与流水号排序，保证同一份数据每次得到同一串结果。
    账本若出现「减仓超过当时持仓」这类不可能的记录，说明数据被绕过服务层写入，
    这里抛 `InvariantViolation`，不继续算出一份看似正常的账。

    `side` 是持仓方向，整条账本共用同一个方向；已实现盈亏按它区分多空口径。
    """

    ordered = sorted(trades, key=lambda row: (row.occurred_at, row.created_at, row.trade_id))
    quantity = Decimal(0)
    avg_cost = Decimal(0)
    status = CLOSED
    projections: list[TradeProjection] = []
    for trade in ordered:
        if status == CLOSED and trade.action in {"add", "reduce", "close"}:
            raise InvariantViolation(f"流水 {trade.trade_id} 发生在已平仓持仓上, 账本无法重放")
        try:
            effect = apply_trade(
                action=trade.action,
                side=side,
                current_quantity=quantity,
                current_avg_cost=avg_cost,
                quantity=trade.quantity,
                price=trade.price,
                fee=trade.fee,
            )
        except (ValidationError, UnprocessableEntity) as exc:
            raise InvariantViolation(f"流水 {trade.trade_id} 无法按账本口径重放:{exc}") from exc
        quantity = effect.quantity
        avg_cost = effect.avg_cost
        status = effect.status
        projections.append(
            TradeProjection(
                trade=trade,
                quantity_after=quantity,
                avg_cost_after=avg_cost,
                status_after=status,
                realized_pnl=effect.realized_pnl,
            )
        )
    return projections


def _require_ledger_inputs(
    *,
    action: str,
    side: str,
    current_quantity: Decimal,
    current_avg_cost: Decimal,
    quantity: Decimal,
    price: Decimal,
    fee: Decimal,
) -> None:
    """先拒绝不可能的输入，再进入按动作分派的计算。"""

    if action not in _SIDE_EFFECTS:
        raise ValidationError(f"不支持的手动持仓动作 {action!r}")
    if side not in _SIDES:
        raise ValidationError(f"持仓方向必须是 long 或 short, 实际 {side!r}")
    if current_quantity < 0:
        raise ValidationError("当前持仓数量不能为负")
    if current_avg_cost < 0:
        raise ValidationError("当前持仓成本不能为负")
    if quantity <= 0:
        raise ValidationError("数量必须大于 0")
    if price <= 0:
        raise ValidationError("成交价必须大于 0")
    if fee < 0:
        raise ValidationError("手续费不能为负")
    if action in {"open", "add"} and current_quantity == 0 and action == "add":
        raise ValidationError("已平仓的持仓不能再加仓")

"""paper 撮合：真实行情 + 手续费 + 滑点，不产生任何真实交易。

## 撮合规则（固定输入必然固定输出，不用随机数）

- **市价单**：以调用方给的市场价为基准，买入上浮一个滑点、卖出下浮一个滑点。
- **限价单**：滑点后的价格仍满足限价才成交（买价不高于限价、卖价不低于限价），否则
  订单停在 `open` 等撤单；成交价取滑点后的价格，不拿限价冒充成交价。
- **手续费**：`成交价 × 成交量 × 费率`，币种按标的取（永续按结算币种、现货按报价币种）。
- **一次撮合成交全部剩余数量**：paper 不模拟行情深度与排队，因此没有部分成交；
  部分成交的累加由 `app.execution.orders.apply_fill` 负责，两条路径共用。

## 与真实下单同一个订单对象

撮合结果写进 `app.execution.orders.Order`——与交易所路径完全同一个类型，区别只在
成交来源：这里没有上游。因此上层（同步、日志、界面）不需要为 paper 单独写一套读取。

## 幂等

`client_order_id` 是这张模拟订单的键。同一个键重放只返回已存在的订单，不产生第二张单、
不重复成交、不改持仓；同一个键配另一份意图（标的、方向、类型、数量、价格、持仓方向或
「只减仓」不同）直接报 `ValidationError`——那是调用方拿错了键，不能拿旧订单冒充新订单。

**唯一例外是「拒单且没有成交」**：账本拒绝（可减持仓不足）或参数与类别不符（例如现货带
`reduce_only`）时，订单落 `failed` 且一笔都没成交，这张单等于没有存在过，同一个键可以改
正参数后重试。已经有成交的失败单不能重试，否则会把已成交的部分再成交一遍。这与 `T5.1`
的拒单口径一致：拒单的幂等键允许再次尝试，已提交的不行。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.core import Fill, Money, OrderIntent, ValidationError
from app.execution.errors import PaperRejected
from app.execution.orders import (
    STATUS_FAILED,
    Order,
    accept,
    apply_fill,
    cancel,
    fail,
    new_order,
)
from app.execution.positions import AccountPosition, PositionBook
from app.instrument import Instrument

__all__ = ["PaperBroker"]

ZERO = Decimal(0)
ONE = Decimal(1)
BUY = "buy"


class PaperBroker:
    """模拟盘撮合器：按注入的行情价、费率与滑点把意图变成订单与成交。"""

    def __init__(self, *, fee_rate: Decimal, slippage: Decimal) -> None:
        self._fee_rate = _require_rate(fee_rate, "手续费率")
        self._slippage = _require_rate(slippage, "滑点率")
        self._orders: dict[str, Order] = {}
        self._fills: dict[str, list[Fill]] = {}
        self._book = PositionBook()
        self._sequence = 0

    # ------------------------------------------------------------------ 下单与撤单

    def place(
        self,
        intent: OrderIntent,
        instrument: Instrument,
        *,
        market_price: Decimal,
        now: datetime,
    ) -> Order:
        """按意图下单并撮合；同一个 `client_order_id` 重放不会产生第二张单。"""

        if not intent.client_order_id:
            raise ValidationError("paper 下单必须给出 client_order_id(幂等键)")
        if intent.inst_id != instrument.symbol:
            raise ValidationError(
                f"意图的标的 {intent.inst_id} 与标的行 {instrument.symbol} 不一致"
            )
        existing = self._orders.get(intent.client_order_id)
        if existing is not None:
            if existing.status == STATUS_FAILED and existing.filled_qty == ZERO:
                # 拒单且没有成交：这张单等于没存在过，同一个键可以改正参数后重试。
                # 与 T5.1 的拒单口径一致（`rejected` 的幂等键允许再次尝试）；已经
                # 有成交的失败单不能重试，否则会把已成交部分再成交一遍。
                del self._orders[intent.client_order_id]
            else:
                _require_same_intent(existing, intent)
                return existing
        if market_price <= ZERO:
            raise ValidationError(f"行情价格必须为正, 实际 {market_price}")
        order = accept(new_order(intent, now=now), self._next_id("paper"), now=now)
        self._orders[order.client_order_id] = order
        price = match_price(order, market_price=market_price, slippage=self._slippage)
        if price is None:
            return order  # 限价单不满足限价：挂着等撤单
        fill = Fill(
            fill_id=self._next_id("pfill"),
            order_id=order.order_id,
            inst_id=order.inst_id,
            side=order.side,
            qty=order.remaining_qty,
            price=price,
            fee=Money(price * order.remaining_qty * self._fee_rate, _fee_currency(instrument)),
            ts=now,
        )
        try:
            self._book.apply(
                fill,
                instrument,
                pos_side=intent.pos_side,
                reduce_only=intent.reduce_only,
            )
        except (PaperRejected, ValidationError):
            # 账本拒绝（可减持仓不足）或参数与类别不符（例如现货带 reduce_only）：
            # 订单落 failed，不留一张永远不成交的 open 单；同一个键改正参数后可重试。
            self._orders[order.client_order_id] = fail(order, now=now)
            raise
        order = apply_fill(order, fill, now=now)
        self._orders[order.client_order_id] = order
        self._fills.setdefault(order.client_order_id, []).append(fill)
        return order

    def cancel(self, client_order_id: str, *, now: datetime) -> Order:
        """撤单：已成交的部分保留，未成交的部分作废。"""

        order = self._orders.get(client_order_id)
        if order is None:
            raise ValidationError(f"没有登记过的模拟订单:{client_order_id}")
        cancelled = cancel(order, now=now)
        self._orders[client_order_id] = cancelled
        return cancelled

    # ---------------------------------------------------------------------- 查询

    def order(self, client_order_id: str) -> Order | None:
        return self._orders.get(client_order_id)

    def orders(self) -> tuple[Order, ...]:
        return tuple(self._orders[key] for key in sorted(self._orders))

    def fills(self, client_order_id: str) -> tuple[Fill, ...]:
        return tuple(self._fills.get(client_order_id, ()))

    def positions(self) -> tuple[AccountPosition, ...]:
        return self._book.positions()

    # ---------------------------------------------------------------------- 内部

    def _next_id(self, prefix: str) -> str:
        """模拟盘没有上游订单号，自己按调用顺序发：同一串调用必然得到同一串编号。"""

        self._sequence += 1
        return f"{prefix}{self._sequence:08d}"


def match_price(order: Order, *, market_price: Decimal, slippage: Decimal) -> Decimal | None:
    """撮合价；限价单不满足限价时返回 `None`（订单挂着等撤单）。

    滑点方向与交易方向相反才对：买入付出更差的（更高）价格，卖出得到更差的（更低）
    价格。成交价永远取滑点后的市场价，不取限价——限价只决定「能不能成交」。
    """

    if order.side == BUY:
        moved = market_price * (ONE + slippage)
        if _below_limit(order, moved):
            return None
        return moved
    moved = market_price * (ONE - slippage)
    if _above_limit(order, moved):
        return None
    return moved


def _below_limit(order: Order, moved: Decimal) -> bool:
    """买单的限价低于滑点后的价格：不可成交。"""

    return order.order_type == "limit" and order.price is not None and order.price < moved


def _above_limit(order: Order, moved: Decimal) -> bool:
    """卖单的限价高于滑点后的价格：不可成交。"""

    return order.order_type == "limit" and order.price is not None and order.price > moved


def _require_rate(value: Decimal, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise ValidationError(f"{name} 必须是 Decimal, 实际 {type(value).__name__}")
    if not value.is_finite() or not ZERO <= value < ONE:
        raise ValidationError(f"{name} 必须在 0 与 1 之间, 实际 {value}")
    return value


def _fee_currency(instrument: Instrument) -> str:
    """手续费币种：永续按结算币种扣，现货按报价币种扣。"""

    return instrument.settle_ccy or instrument.quote_currency


def _require_same_intent(order: Order, intent: OrderIntent) -> None:
    """同一个幂等键只能对应同一个意图；不一致就报错，不拿旧订单冒充新订单。"""

    wanted = {
        "inst_id": intent.inst_id,
        "side": intent.side,
        "order_type": intent.order_type,
        "qty": intent.qty,
        "price": intent.price,
        "pos_side": intent.pos_side,
        "reduce_only": intent.reduce_only,
    }
    recorded = {
        "inst_id": order.inst_id,
        "side": order.side,
        "order_type": order.order_type,
        "qty": order.qty,
        "price": order.price,
        "pos_side": order.pos_side,
        "reduce_only": order.reduce_only,
    }
    differs = sorted(name for name in wanted if wanted[name] != recorded[name])
    if differs:
        raise ValidationError(
            f"client_order_id {intent.client_order_id} 已用于另一个订单意图,"
            f" 不一致的字段: {', '.join(differs)}"
        )

"""订单状态机与部分成交累加（纯函数，无 IO）。

## 状态与合法转移

本节点定稿的状态集合与转移表就是 `LEGAL_TRANSITIONS`，全部状态由 `ORDER_STATUSES`
派生，不再有第二份清单：

    pending ──▶ open ──▶ partially_filled ──▶ filled
       │         │              │
       ├──▶ cancelled ◀─────────┤
       └──▶ failed    ◀─────────┘

- `partially_filled → partially_filled` 是合法自环：又来一笔部分成交，状态不变、
  数量累加。把它写进转移表，是因为「状态没变」本身也是一次需要校验的转移。
- `filled` / `cancelled` / `failed` 是终态，没有任何出边。

## 三条判定口径

1. **非法转移一律抛 `ValidationError`**，调用方不许用 `try/except` 把它们吞成放行：
   状态机是唯一会红的地方，上层只处理业务失败（拒单、上游故障）。
2. **部分成交累加而不是覆盖**：`filled_qty` 是历史成交量之和，`filled_cost` 是
   `Σ 成交量 × 成交价`，加权成交均价由两者相除得到。覆盖式写法在下一笔部分成交时
   会把前几笔成交量抹掉，账本与交易所永远对不平。
3. **状态与成交量必须自洽**：`pending` 与 `open` 没有成交，`partially_filled` 有成交
   但没满，`filled` 必须满。自洽性在构造时校验，因此不存在「状态是 `filled` 但
   `filled_qty` 只有一半」的订单流到下游。

订单对象只有一种：真实下单经 `from_venue_order` 归一后与 paper 撮合产出同一个
`Order` 类型，区别只在成交从哪来。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from app.core import Fill, OrderIntent, ValidationError
from app.core import Order as VenueOrder

__all__ = [
    "LEGAL_TRANSITIONS",
    "ORDER_STATUSES",
    "STATUS_CANCELLED",
    "STATUS_FAILED",
    "STATUS_FILLED",
    "STATUS_OPEN",
    "STATUS_PARTIALLY_FILLED",
    "STATUS_PENDING",
    "TERMINAL_STATUSES",
    "VENUE_ORDER_STATUSES",
    "Order",
    "accept",
    "apply_fill",
    "cancel",
    "fail",
    "from_venue_order",
    "new_order",
    "require_transition",
]

#: 已登记或已提交，撮合方还没受理。
STATUS_PENDING = "pending"
#: 撮合方已受理，还没有成交。
STATUS_OPEN = "open"
#: 已成交一部分，还有剩余数量。
STATUS_PARTIALLY_FILLED = "partially_filled"
#: 全部成交。
STATUS_FILLED = "filled"
#: 被撤单；已成交的部分保留。
STATUS_CANCELLED = "cancelled"
#: 被拒或超时失败；已成交的部分保留。
STATUS_FAILED = "failed"

ORDER_STATUSES: frozenset[str] = frozenset(
    {
        STATUS_PENDING,
        STATUS_OPEN,
        STATUS_PARTIALLY_FILLED,
        STATUS_FILLED,
        STATUS_CANCELLED,
        STATUS_FAILED,
    }
)

#: 终态：订单到此为止，不再接受任何转移。
TERMINAL_STATUSES: frozenset[str] = frozenset({STATUS_FILLED, STATUS_CANCELLED, STATUS_FAILED})

#: 转移表：当前状态 → 允许到达的下一个状态。终态对应空集。
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_PENDING: frozenset({STATUS_OPEN, STATUS_CANCELLED, STATUS_FAILED}),
    STATUS_OPEN: frozenset(
        {STATUS_PARTIALLY_FILLED, STATUS_FILLED, STATUS_CANCELLED, STATUS_FAILED}
    ),
    STATUS_PARTIALLY_FILLED: frozenset(
        {STATUS_PARTIALLY_FILLED, STATUS_FILLED, STATUS_CANCELLED, STATUS_FAILED}
    ),
    STATUS_FILLED: frozenset(),
    STATUS_CANCELLED: frozenset(),
    STATUS_FAILED: frozenset(),
}

ORDER_SIDES: frozenset[str] = frozenset({"buy", "sell"})
ORDER_TYPES: frozenset[str] = frozenset({"market", "limit"})
#: 永续的持仓方向；`net` 是单向持仓模式。现货订单必须留空。
POS_SIDES: frozenset[str] = frozenset({"long", "short", "net"})

#: 上游订单状态 → 执行域状态。上游保留自己的字面量（`live` / `canceled`），执行域
#: 必须先翻成本模块的词表，否则同一个状态在两条路径上有两个名字，上层要再写一层映射。
VENUE_ORDER_STATUSES: dict[str, str] = {
    "live": STATUS_OPEN,
    "partially_filled": STATUS_PARTIALLY_FILLED,
    "filled": STATUS_FILLED,
    "canceled": STATUS_CANCELLED,
    "mmp_canceled": STATUS_CANCELLED,
}

ZERO = Decimal(0)


def require_transition(current: str, target: str) -> None:
    """校验一次状态转移；非法转移（含未知状态）抛 `ValidationError`。"""

    if current not in LEGAL_TRANSITIONS:
        raise ValidationError(f"未知订单状态 {current!r}")
    if target not in LEGAL_TRANSITIONS:
        raise ValidationError(f"未知订单状态 {target!r}")
    if target not in LEGAL_TRANSITIONS[current]:
        raise ValidationError(f"订单状态不能从 {current} 转移到 {target}")


@dataclass(frozen=True, slots=True)
class Order:
    """执行域的一张订单。

    `client_order_id` 是幂等键，也是 paper 侧查单的身份；`order_id` 是撮合方给出的
    订单号，`pending` 阶段还没有。成交金额只在这里累加成两个量（数量与金额），
    加权均价与剩余数量都是派生值，避免出现「均价与金额各写一份，改了一处忘另一处」。

    `pos_side` 与 `reduce_only` 是意图的一部分：它们决定这笔成交落在哪条腿、是加仓还是
    平仓，因此也参与幂等重放时的一致性判断——只改这两项也算另一个意图，不能当重放。
    """

    client_order_id: str
    inst_id: str
    side: str
    order_type: str
    qty: Decimal
    price: Decimal | None
    created_at: datetime
    updated_at: datetime
    order_id: str = ""
    #: 永续的持仓方向（对冲模式为 long / short，单向模式为 net）；现货留空。
    pos_side: str = ""
    #: 只减仓：这笔成交只能用来了结已有持仓。
    reduce_only: bool = False
    status: str = STATUS_PENDING
    filled_qty: Decimal = ZERO
    filled_cost: Decimal = ZERO

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise ValidationError("订单必须有 client_order_id")
        if not self.inst_id.strip():
            raise ValidationError("订单必须给出 inst_id")
        if self.side not in ORDER_SIDES:
            raise ValidationError(f"下单方向必须是 {sorted(ORDER_SIDES)}, 实际 {self.side!r}")
        if self.order_type not in ORDER_TYPES:
            raise ValidationError(f"订单类型必须是 {sorted(ORDER_TYPES)}, 实际 {self.order_type!r}")
        if self.pos_side and self.pos_side not in POS_SIDES:
            raise ValidationError(f"持仓方向必须是 {sorted(POS_SIDES)}, 实际 {self.pos_side!r}")
        if not isinstance(self.reduce_only, bool):
            raise ValidationError(
                f"reduce_only 必须是布尔值, 实际 {type(self.reduce_only).__name__}"
            )
        if self.qty <= ZERO:
            raise ValidationError(f"订单数量必须为正, 实际 {self.qty}")
        _require_price(self.order_type, self.price)
        if self.status not in ORDER_STATUSES:
            raise ValidationError(f"未知订单状态 {self.status!r}")
        if not ZERO <= self.filled_qty <= self.qty:
            raise ValidationError(f"已成交量 {self.filled_qty} 不在 0 与 {self.qty} 之间")
        if self.filled_cost < ZERO:
            raise ValidationError(f"成交金额不能为负, 实际 {self.filled_cost}")
        for name in ("created_at", "updated_at"):
            if getattr(self, name).tzinfo is None:
                raise ValidationError(f"订单的 {name} 必须带时区")
        if self.updated_at < self.created_at:
            raise ValidationError(f"订单的 updated_at 早于 created_at:{self.updated_at}")
        self._require_status_matches_fills()

    def _require_status_matches_fills(self) -> None:
        """状态与成交量必须自洽：不让「状态说成交了、数量说没有」的订单流到下游。"""

        filled = self.filled_qty
        if self.status in {STATUS_PENDING, STATUS_OPEN} and filled != ZERO:
            raise ValidationError(f"{self.status} 的订单不能已有成交量 {filled}")
        if self.status == STATUS_PARTIALLY_FILLED and not ZERO < filled < self.qty:
            raise ValidationError(f"部分成交的订单必须 0 < 已成交量 < {self.qty}, 实际 {filled}")
        if self.status == STATUS_FILLED and filled != self.qty:
            raise ValidationError(f"已成交的订单必须全部成交, 实际 {filled} / {self.qty}")
        if self.status != STATUS_FILLED and filled == self.qty:
            raise ValidationError(f"{self.status} 的订单不能是满额成交")
        if filled == ZERO and self.filled_cost != ZERO:
            raise ValidationError(f"没有成交量却有成交金额 {self.filled_cost}")

    @property
    def remaining_qty(self) -> Decimal:
        """还没成交的数量。"""

        return self.qty - self.filled_qty

    @property
    def avg_fill_price(self) -> Decimal | None:
        """按成交量加权的成交均价；没有成交或成交金额未知时是 `None`，不是 0。"""

        if self.filled_qty == ZERO or self.filled_cost == ZERO:
            return None
        return self.filled_cost / self.filled_qty


def from_venue_order(order: VenueOrder, *, pos_side: str = "", reduce_only: bool = False) -> Order:
    """把交易所侧的一张订单（`core.Order`）归一成本模块的 `Order`。

    真实入口 `TradePort.place()` 返回 `core.Order`，其中 `status` 保留上游字面量
    （`live` / `canceled`）。不归一就会出现两套订单对象：paper 侧用本模块词表，
    真实侧用上游词表，上层必须自己再写一层映射，而把 `live` 直接塞进本模块会被
    当成未知状态拒绝。归一后两条路径产出同一个类型与同一套状态。

    `core.Order` 只有下单时间 `ts`，因此 `created_at` 与 `updated_at` 都取它；
    它也不带成交金额，`filled_cost` 保持 0（未知），成交均价由调用方按成交记录另算，
    这里不编造一个看起来有效的成本。

    `core.Order` 同样不带持仓腿与平仓方向，而这两项决定成交落在哪条腿、是开仓还是
    平仓，不能按空值猜：永续的对冲模式与只减仓订单必须由调用方按原下单意图显式传入。
    留空表示单向模式且非只减仓，与现货订单的默认值一致。
    """

    status = VENUE_ORDER_STATUSES.get(order.status)
    if status is None:
        raise ValidationError(f"未知的交易所订单状态 {order.status!r}")
    return Order(
        client_order_id=order.client_order_id,
        inst_id=order.inst_id,
        side=order.side,
        order_type=order.order_type,
        qty=order.qty,
        price=order.price,
        created_at=order.ts,
        updated_at=order.ts,
        order_id=order.order_id,
        pos_side=pos_side,
        reduce_only=reduce_only,
        status=status,
        filled_qty=order.filled_qty,
    )


def new_order(intent: OrderIntent, *, now: datetime) -> Order:
    """按意图建一张 `pending` 订单：本地已登记，还没送到撮合方。"""

    return Order(
        client_order_id=intent.client_order_id,
        inst_id=intent.inst_id,
        side=intent.side,
        order_type=intent.order_type,
        qty=intent.qty,
        price=intent.price,
        pos_side=intent.pos_side,
        reduce_only=intent.reduce_only,
        created_at=now,
        updated_at=now,
    )


def accept(order: Order, order_id: str, *, now: datetime) -> Order:
    """撮合方受理：`pending → open`，同时记下撮合方给的订单号。"""

    if not order_id.strip():
        raise ValidationError("受理订单必须给出撮合方订单号")
    require_transition(order.status, STATUS_OPEN)
    return replace(order, status=STATUS_OPEN, order_id=order_id, updated_at=now)


def apply_fill(order: Order, fill: Fill, *, now: datetime) -> Order:
    """累加一笔成交：数量与金额相加，状态按剩余量推进。"""

    _require_same_order(order, fill)
    if fill.qty <= ZERO:
        raise ValidationError(f"成交数量必须为正, 实际 {fill.qty}")
    if fill.price <= ZERO:
        raise ValidationError(f"成交价必须为正, 实际 {fill.price}")
    filled = order.filled_qty + fill.qty
    if filled > order.qty:
        raise ValidationError(f"成交总量 {filled} 超过订单数量 {order.qty}")
    target = STATUS_FILLED if filled == order.qty else STATUS_PARTIALLY_FILLED
    require_transition(order.status, target)
    return replace(
        order,
        status=target,
        filled_qty=filled,
        filled_cost=order.filled_cost + fill.qty * fill.price,
        updated_at=now,
    )


def cancel(order: Order, *, now: datetime) -> Order:
    """撤单：已成交的部分原样保留，不会被抹成 0。"""

    require_transition(order.status, STATUS_CANCELLED)
    return replace(order, status=STATUS_CANCELLED, updated_at=now)


def fail(order: Order, *, now: datetime) -> Order:
    """置为失败：已成交的部分原样保留，用于拒单与超时。"""

    require_transition(order.status, STATUS_FAILED)
    return replace(order, status=STATUS_FAILED, updated_at=now)


def _require_price(order_type: str, price: Decimal | None) -> None:
    if order_type == "limit":
        if price is None:
            raise ValidationError("限价单必须给出 price")
        if price <= ZERO:
            raise ValidationError(f"限价必须为正, 实际 {price}")
        return
    if price is not None:
        raise ValidationError("市价单不能给出 price")


def _require_same_order(order: Order, fill: Fill) -> None:
    """成交必须属于这张订单：标的、方向、订单号三项都要对得上。"""

    if fill.inst_id != order.inst_id:
        raise ValidationError(f"成交的标的 {fill.inst_id} 与订单 {order.inst_id} 不一致")
    if fill.side != order.side:
        raise ValidationError(f"成交方向 {fill.side} 与订单方向 {order.side} 不一致")
    if order.order_id and fill.order_id and fill.order_id != order.order_id:
        raise ValidationError(f"成交的订单号 {fill.order_id} 与订单号 {order.order_id} 不一致")

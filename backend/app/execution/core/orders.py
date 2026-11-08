"""订单状态机与成交累加（纯函数）。

状态机是全系统唯一的订单状态权威：数据库里的 `execution.order.state` 只允许
按 `ALLOWED_TRANSITIONS` 迁移，非法迁移抛 `OrderStateError` 且不改变原状态。

合法路径：

    pending → submitted → partial → filled
                        ↘ filled / canceled / rejected
    pending → rejected / canceled（未成功发出即失败）
"""

from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal("0")

ORDER_STATES = ("pending", "submitted", "partial", "filled", "canceled", "rejected")
TERMINAL_STATES = frozenset({"filled", "canceled", "rejected"})

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"submitted", "rejected", "canceled"}),
    "submitted": frozenset({"partial", "filled", "canceled", "rejected"}),
    "partial": frozenset({"partial", "filled", "canceled"}),
    "filled": frozenset(),
    "canceled": frozenset(),
    "rejected": frozenset(),
}

# OKX `state` → 本项目状态。未知取值由调用方按失败处理，绝不静默猜测。
EXCHANGE_STATE_MAP: dict[str, str] = {
    "live": "submitted",
    "partially_filled": "partial",
    "filled": "filled",
    "canceled": "canceled",
    "cancelled": "canceled",
    "mmp_canceled": "canceled",
    "rejected": "rejected",
}


class OrderStateError(ValueError):
    """非法状态迁移；`code` 用于 API 错误信封。"""

    code = "execution_invalid_transition"

    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"订单状态不允许从 {current} 迁移到 {target}")
        self.current = current
        self.target = target


def can_transition(current: str, target: str) -> bool:
    """判断一次迁移是否合法；未知状态一律视为非法。"""

    if current not in ALLOWED_TRANSITIONS:
        return False
    return target in ALLOWED_TRANSITIONS[current]


def ensure_transition(current: str, target: str) -> str:
    """校验迁移并返回目标状态；非法时抛错且不产生副作用。"""

    if not can_transition(current, target):
        raise OrderStateError(current, target)
    return target


def normalize_exchange_state(raw: str) -> str:
    """把交易所状态映射为本项目状态；未知状态直接报错。"""

    try:
        return EXCHANGE_STATE_MAP[raw]
    except KeyError as exc:
        raise OrderStateError(raw, "unknown") from exc


@dataclass(frozen=True, slots=True)
class OrderSnapshot:
    """订单的成交累加视图；与 ORM 行解耦，便于纯函数断言。"""

    state: str
    quantity: Decimal
    filled_quantity: Decimal
    average_price: Decimal
    fee: Decimal


def apply_fill(
    snapshot: OrderSnapshot,
    *,
    quantity: Decimal,
    price: Decimal,
    fee: Decimal = ZERO,
) -> OrderSnapshot:
    """把一笔成交累加到订单视图，返回新视图。

    成交数量超过订单数量属于数据错误，直接报错而不是截断——截断会掩盖
    对账差异，且会让持仓与订单永久不一致。
    """

    if quantity <= ZERO or price <= ZERO:
        raise OrderStateError(snapshot.state, "invalid_fill")
    total = snapshot.filled_quantity + quantity
    if total > snapshot.quantity:
        raise OrderStateError(snapshot.state, "over_filled")

    target = "filled" if total == snapshot.quantity else "partial"
    state = ensure_transition(snapshot.state, target)
    notional = snapshot.average_price * snapshot.filled_quantity + price * quantity
    average = notional / total
    return OrderSnapshot(
        state=state,
        quantity=snapshot.quantity,
        filled_quantity=total,
        average_price=average,
        fee=snapshot.fee + fee,
    )


__all__ = [
    "ALLOWED_TRANSITIONS",
    "EXCHANGE_STATE_MAP",
    "ORDER_STATES",
    "TERMINAL_STATES",
    "OrderSnapshot",
    "OrderStateError",
    "apply_fill",
    "can_transition",
    "ensure_transition",
    "normalize_exchange_state",
]

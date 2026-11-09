"""`execute_strategy_action` 的动作语义（纯函数，无 IO）。

交易所在方向、平仓与仓位约束上的规则必须可断言，所以这里只做一件事：
把 `(action, side/position_side, quantity, available)` 映射成一条订单参数，
非法组合直接拒绝。任何 IO 都不在这里发生，调用方负责查持仓与落单。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

ZERO = Decimal("0")

ACTIONS: tuple[str, ...] = ("open", "increase", "reduce", "close", "stop")

# action -> (intent, reduce_only)
_MODES: dict[str, tuple[str, bool]] = {
    "open": ("entry", False),
    "increase": ("entry", False),
    "reduce": ("exit", True),
    "close": ("exit", True),
    "stop": ("stop", True),
}

_LONG_OF_SIDE = {"buy": "long", "sell": "short"}
_SIDE_OF_LONG = {"long": "buy", "short": "sell"}
_OPPOSITE_SIDE = {"buy": "sell", "sell": "buy"}


class ActionError(Exception):
    """动作参数不合法；`code` 直接作为 tools/call 的 `error_code`。"""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class OrderPlan:
    """一条待提交订单的参数（不含策略/标的，那两者由调用方给出）。"""

    side: str
    position_side: str
    quantity: Decimal
    intent: str
    reduce_only: bool


def parse_quantity(value: Any) -> Decimal | None:
    """JSON 数字/字符串统一成 Decimal；非法、NaN、非正数返回 None。"""

    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number <= ZERO:
        return None
    return number


def _directions(action: str, side: str | None, position_side: str | None) -> tuple[str, str]:
    """确定 (side, position_side)；两个方向参数互相矛盾时拒绝。"""

    if side is not None and side not in _LONG_OF_SIDE:
        raise ActionError("invalid_action", f"side must be buy or sell, got {side!r}")
    if position_side is not None and position_side not in _SIDE_OF_LONG:
        raise ActionError(
            "invalid_action", f"position_side must be long or short, got {position_side!r}"
        )
    if side is not None and position_side is not None:
        if _LONG_OF_SIDE[side] != position_side:
            raise ActionError(
                "action_side_conflict",
                "side and position_side disagree",
                details={"side": side, "position_side": position_side},
            )
        return side, position_side
    if side is not None:
        return side, _LONG_OF_SIDE[side]
    if position_side is not None:
        return _SIDE_OF_LONG[position_side], position_side
    raise ActionError(
        "action_side_required",
        "provide side (buy/sell) or position_side (long/short)",
        details={"action": action},
    )


def plan_action(
    action: str,
    *,
    side: str | None = None,
    position_side: str | None = None,
    quantity: Any = None,
    available: Decimal | None = None,
) -> OrderPlan:
    """把动作映射成订单参数；`available` 是该方向当前可平数量（无持仓为 0）。"""

    if action not in ACTIONS:
        raise ActionError(
            "invalid_action",
            f"action must be one of {', '.join(ACTIONS)}, got {action!r}",
            details={"action": action},
        )

    held = available if available is not None and available > ZERO else None
    intent, reduce_only = _MODES[action]

    if action in {"reduce", "close", "stop"}:
        if position_side is None:
            raise ActionError(
                "action_position_side_required",
                f"{action} needs position_side (the side to reduce/close)",
                details={"action": action},
            )
        if held is None:
            raise ActionError(
                "no_position",
                f"{action} 需要该方向已有持仓",
                details={"action": action, "position_side": position_side},
            )
        # 平仓类动作的下单方向永远与持仓方向相反。
        order_side = _OPPOSITE_SIDE[_SIDE_OF_LONG[position_side]]
        requested = parse_quantity(quantity)
        if action in {"close", "stop"}:
            if requested is not None and requested != held:
                raise ActionError(
                    "action_quantity_mismatch",
                    f"{action} 必须一次平掉全部持仓",
                    details={"requested": str(requested), "available": str(held)},
                )
            return OrderPlan(
                side=order_side,
                position_side=position_side,
                quantity=held,
                intent=intent,
                reduce_only=reduce_only,
            )
        if requested is None:
            raise ActionError(
                "action_quantity_required",
                "reduce 需要正数量",
                details={"action": action},
            )
        if requested > held:
            raise ActionError(
                "exceeds_position",
                "reduce 数量超过当前持仓",
                details={"requested": str(requested), "available": str(held)},
            )
        return OrderPlan(
            side=order_side,
            position_side=position_side,
            quantity=requested,
            intent=intent,
            reduce_only=reduce_only,
        )

    order_side, resolved_position_side = _directions(action, side, position_side)
    requested = parse_quantity(quantity)
    if requested is None:
        raise ActionError(
            "action_quantity_required",
            f"{action} 需要正数量",
            details={"action": action},
        )
    if action == "increase" and held is None:
        raise ActionError(
            "no_position",
            "increase 需要该方向已有持仓",
            details={"action": action, "position_side": resolved_position_side},
        )
    return OrderPlan(
        side=order_side,
        position_side=resolved_position_side,
        quantity=requested,
        intent=intent,
        reduce_only=reduce_only,
    )


__all__ = [
    "ACTIONS",
    "ZERO",
    "ActionError",
    "OrderPlan",
    "parse_quantity",
    "plan_action",
]

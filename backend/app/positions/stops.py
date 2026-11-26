"""把交易所回传的止盈止损委托对齐到持仓，并给出三态结论。

这里只做纯计算：输入是持仓快照与 `stop_orders()` 的结果，输出是每一条持仓的止损
状态。网络与落库都在 `service` 里，本模块不碰 IO，方便直接断言。

三种状态必须分开，这是本模块存在的理由：

- `confirmed`：确实查到止损触发价，`px` 有值；
- `none`：四类策略委托与订单都问过了，这条持仓确实没有止损；
- `unavailable`：这次没问到（上游失败或没同步过）。把它写成 `none` 就是在告诉
  用户「你没设止损」，而事实是「不知道」。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.core import ExchangePosition, StopOrder

__all__ = [
    "STOP_CONFIRMED",
    "STOP_NONE",
    "STOP_UNAVAILABLE",
    "StopState",
    "resolve_stop_states",
]

STOP_CONFIRMED = "confirmed"
STOP_NONE = "none"
STOP_UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class StopState:
    """一条持仓的止损结论；`px` 只在 `confirmed` 时有值。"""

    status: str
    px: Decimal | None


def resolve_stop_states(
    positions: Sequence[ExchangePosition],
    stops: Sequence[StopOrder],
    *,
    available: bool,
) -> dict[str, StopState]:
    """`pos_id` → 止损状态。

    `available=False` 表示这一次没能取到止损数据，所有持仓一律 `unavailable`。

    匹配口径：先按标的聚合止损触发价，`posSide` 明确的委托只在同向持仓上生效；
    一条持仓有多个止损时取**离标记价最近**的那个（差价相同取较低价位），保证同一份
    输入永远得到同一个结果，不依赖上游返回顺序。
    """

    if not available:
        return {item.pos_id: StopState(STOP_UNAVAILABLE, None) for item in positions}

    by_symbol: dict[str, list[tuple[Decimal, str | None]]] = {}
    for order in stops:
        if order.stop_px is None:
            continue
        by_symbol.setdefault(order.inst_id, []).append(
            (order.stop_px, _normalized_side(order.pos_side))
        )

    states: dict[str, StopState] = {}
    for position in positions:
        candidates = _candidates(by_symbol.get(position.inst_id, ()), position.pos_side)
        if not candidates:
            states[position.pos_id] = StopState(STOP_NONE, None)
            continue
        states[position.pos_id] = StopState(STOP_CONFIRMED, _closest(candidates, position.mark_px))
    return states


def _normalized_side(value: str | None) -> str | None:
    """`net`（单向持仓模式的委托）不限定方向。"""

    if value in {"long", "short"}:
        return value
    return None


def _candidates(
    prices: Sequence[tuple[Decimal, str | None]],
    side: str,
) -> list[Decimal]:
    return [price for price, order_side in prices if order_side is None or order_side == side]


def _closest(prices: Sequence[Decimal], mark_px: Decimal | None) -> Decimal:
    if mark_px is None:
        return min(prices)
    return min(prices, key=lambda price: (abs(price - mark_px), price))

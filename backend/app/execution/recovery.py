"""重启后的状态恢复：以交易所快照为准重建本地订单、成交与持仓。

## 恢复什么

- **未完成订单**：交易所侧仍存在、状态是挂单或部分成交的订单，重建后继续保留，
  调用方据此知道「这张单还没走完」。
- **部分成交**：按成交记录逐笔累加，`filled_qty` 是历史成交量之和，不是最后一笔
  的覆盖值。
- **账户实际持仓**：直接采用本次快照；快照没有取持仓时保留本地持仓。
- **新成交**：`new_fills` 只含本地状态里还没有的成交。调用方把它记进策略虚拟账本，
  就能让两侧收敛；同一份快照恢复两次时 `new_fills` 为空，不会重复记账。

## 不做什么

- 不产生新订单，也不重发旧订单；重复下单由 `clientOrderId` 的幂等登记挡住。
- 不修改虚拟账本：策略级持仓归组合管理，本模块只交出新成交的增量。
- 不做对账差额清单：那是 `reconcile` 的职责。

## 与同步的关系

恢复复用 `sync_state` 的收敛规则：上游才是事实来源，本地订单按「上游订单 + 全部
成交」重建；本地有、上游没有的非终态订单置 `failed`。恢复只是在此基础上补上
「哪些订单还没走完、哪些成交是新出现的」这两个视图。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.core import Fill, ValidationError
from app.execution.model import ExecutionState, VenueSnapshot
from app.execution.orders import (
    STATUS_PARTIALLY_FILLED,
    TERMINAL_STATUSES,
    Order,
)
from app.execution.sync import sync_state

__all__ = ["RecoveredState", "recover_state"]

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class RecoveredState:
    """一次恢复的结果：收敛后的本地状态与需要下游继续处理的增量。"""

    state: ExecutionState
    new_fills: tuple[Fill, ...] = ()
    unfinished_orders: tuple[Order, ...] = ()
    partial_orders: tuple[Order, ...] = ()
    failed_client_order_ids: tuple[str, ...] = ()
    as_of: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "new_fills", tuple(self.new_fills))
        object.__setattr__(self, "unfinished_orders", tuple(self.unfinished_orders))
        object.__setattr__(self, "partial_orders", tuple(self.partial_orders))
        object.__setattr__(self, "failed_client_order_ids", tuple(self.failed_client_order_ids))
        if self.as_of is not None and self.as_of.tzinfo is None:
            raise ValidationError("恢复的 as_of 必须带时区")


def recover_state(
    state: ExecutionState,
    snapshot: VenueSnapshot,
    *,
    now: datetime,
) -> RecoveredState:
    """用一份交易所快照恢复本地状态；纯函数，不产生订单。"""

    if now.tzinfo is None:
        raise ValidationError("恢复时间必须带时区")

    new_fills = _new_fills(state.fills, snapshot.fills)
    result = sync_state(state, snapshot, now=now)
    unfinished = tuple(
        order for order in result.state.orders if order.status not in TERMINAL_STATUSES
    )
    partial = tuple(order for order in unfinished if order.status == STATUS_PARTIALLY_FILLED)
    return RecoveredState(
        state=result.state,
        new_fills=new_fills,
        unfinished_orders=unfinished,
        partial_orders=partial,
        failed_client_order_ids=result.failed_client_order_ids,
        as_of=now,
    )


def _new_fills(
    existing: tuple[Fill, ...],
    incoming: tuple[Fill, ...],
) -> tuple[Fill, ...]:
    """取本次新出现的成交，按与同步相同的键去重。"""

    seen = {_fill_key(fill) for fill in existing}
    fresh: list[Fill] = []
    for fill in incoming:
        key = _fill_key(fill)
        if key in seen:
            continue
        seen.add(key)
        fresh.append(fill)
    return tuple(fresh)


def _fill_key(fill: Fill) -> str:
    """有成交号用成交号；没有时用完整字段拼一个稳定键。"""

    if fill.fill_id:
        return fill.fill_id
    return "|".join(
        (
            fill.order_id,
            fill.inst_id,
            fill.side,
            format(fill.qty, "f"),
            format(fill.price, "f"),
            fill.ts.isoformat(),
        )
    )

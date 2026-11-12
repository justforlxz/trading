"""执行编排：交易计划 → 人工确认 → 下单，以及把同步结果写回本地状态。

本层只做 IO 与编排，不判断策略好坏、不绕过风控、不做对账差额清单：

- 下单前必须有一份与当前计划版本匹配的确认记录；没有确认直接抛 `Conflict`，不会
  调用任何后端，因此 paper 与真实两侧都不会出现订单。
- 同一计划版本的每条腿有固定的 `clientOrderId`。重复确认先查本地已登记的订单，
  已有订单直接返回，不再向上游发一次请求。
- 上游拒单或超时一律把本地订单置 `failed`，`retry_count` 保持 0，不自动重发。
  之后由同步按上游事实修正；如果这张单其实已经到达交易所，同步会把它补回来。
- 每条腿的结果在进入下一条腿之前写入本地状态。后续腿抛出任何异常时，前面已经
  下到交易所的订单仍然留在本地状态里，不会出现上游有单、本地无记录的情况。

paper 与真实路径通过 `OrderBackend` 这个很小的端口接入：两者最终都返回
`app.execution.orders.Order`，编排层不需要为两种模式各写一套流程。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from app.core import (
    Clock,
    Conflict,
    ExecutionRejected,
    OrderIntent,
    SystemClock,
    TradePort,
    UpstreamError,
    ValidationError,
)
from app.execution.manual import client_order_id, confirm, require_confirmation
from app.execution.model import (
    ConfirmationRecord,
    ExecutionState,
    Placement,
    PlacementResult,
    SyncResult,
    TradePlan,
    VenueSnapshot,
)
from app.execution.orders import Order, fail, from_venue_order, new_order
from app.execution.paper import PaperBroker
from app.execution.sync import sync_state
from app.instrument import Instrument

__all__ = [
    "ExecutionService",
    "OrderBackend",
    "PaperOrderBackend",
    "TradePortBackend",
    "paper_snapshot",
]


class OrderBackend(Protocol):
    """执行编排需要的最小下单端口。"""

    def place(self, intent: OrderIntent, *, now: datetime) -> Order:
        """按意图下单，返回执行域订单；上游拒单/故障抛 `ExecutionRejected` / `UpstreamError`."""

        raise NotImplementedError


class TradePortBackend:
    """把 `TradePort`（真实交易所）适配成 `OrderBackend`。

    `TradePort.place()` 返回 `core.Order`，状态字面量是上游的 `live` / `canceled`；
    这里用 `from_venue_order` 归一成执行域词表，编排层因此只看到一种订单对象。
    """

    def __init__(self, trade: TradePort) -> None:
        self._trade = trade

    def place(self, intent: OrderIntent, *, now: datetime) -> Order:
        return from_venue_order(
            self._trade.place(intent),
            pos_side=intent.pos_side,
            reduce_only=intent.reduce_only,
        )


class PaperOrderBackend:
    """把 `PaperBroker` 适配成 `OrderBackend`。

    paper 撮合需要标的行与行情价，两者由装配方按 `inst_id` 注入；执行编排不自己读
    数据库或行情，避免把 paper 专用依赖漏到真实路径。
    """

    def __init__(
        self,
        broker: PaperBroker,
        *,
        instruments: Mapping[str, Instrument],
        prices: Mapping[str, Decimal],
    ) -> None:
        self._broker = broker
        self._instruments = dict(instruments)
        self._prices = dict(prices)

    def place(self, intent: OrderIntent, *, now: datetime) -> Order:
        instrument = self._instruments.get(intent.inst_id)
        if instrument is None:
            raise ValidationError(f"paper 下单缺少标的行:{intent.inst_id}")
        market_price = self._prices.get(intent.inst_id)
        if market_price is None:
            raise ValidationError(f"paper 下单缺少行情价:{intent.inst_id}")
        return self._broker.place(intent, instrument, market_price=market_price, now=now)


class ExecutionService:
    """Manual 模式的服务层：确认、下单与同步。"""

    def __init__(self, backend: OrderBackend, *, clock: Clock | None = None) -> None:
        self._backend = backend
        self._clock = clock or SystemClock()
        self._confirmations: dict[tuple[str, int], ConfirmationRecord] = {}
        self._state = ExecutionState()

    @property
    def state(self) -> ExecutionState:
        """当前本地已知的执行状态。"""

        return self._state

    def confirm(self, plan: TradePlan, *, confirmed_by: str) -> ConfirmationRecord:
        """记录人工确认；确认记录按计划与版本保存。"""

        record = confirm(plan, confirmed_by=confirmed_by, now=self._clock.now())
        self._confirmations[(plan.plan_id, plan.version)] = record
        return record

    def place(self, plan: TradePlan) -> PlacementResult:
        """按已确认的计划下单；未确认、确认版本不匹配时拒绝。"""

        record = self._confirmations.get((plan.plan_id, plan.version))
        if record is None:
            raise Conflict("交易计划未确认, 不产生订单")
        require_confirmation(plan, record)

        now = self._clock.now()
        placements: list[Placement] = []
        for leg in plan.legs:
            key = client_order_id(plan, leg)
            existing = self._state.order(key)
            if existing is not None:
                placements.append(
                    Placement(client_order_id=key, order=existing, retry_count=0, reused=True)
                )
                continue
            intent = OrderIntent(
                inst_id=leg.inst_id,
                side=leg.side,
                qty=leg.qty,
                order_type=leg.order_type,
                price=leg.price_cap,
                client_order_id=key,
            )
            try:
                order = self._backend.place(intent, now=now)
            except (ExecutionRejected, UpstreamError) as exc:
                order = fail(new_order(intent, now=now), now=now)
                placements.append(
                    Placement(client_order_id=key, order=order, retry_count=0, error=str(exc))
                )
            else:
                placements.append(Placement(client_order_id=key, order=order))
            self._state = replace(self._state, orders=(*self._state.orders, order))
        return PlacementResult(placements=tuple(placements))

    def sync(self, snapshot: VenueSnapshot) -> SyncResult:
        """用一份上游快照回写本地订单与持仓。"""

        result = sync_state(self._state, snapshot, now=self._clock.now())
        self._state = result.state
        return result


def paper_snapshot(broker: PaperBroker) -> VenueSnapshot:
    """把 paper 账本当前状态整理成同步快照。"""

    orders = broker.orders()
    fills = tuple(fill for order in orders for fill in broker.fills(order.client_order_id))
    return VenueSnapshot(orders=orders, fills=fills, positions=broker.positions())

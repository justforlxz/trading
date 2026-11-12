"""订单与持仓同步：以交易所或 paper 账本的实际状态为准回写本地。

## 两个方向都必须覆盖

- **本地有单、上游没有**：本地还在 `pending` / `open` / `partially_filled` 的订单
  说明上游已经没有这张单，按上游事实置 `failed`；已经终结的订单保持原样。
- **上游有单、本地没有**：从上游订单补出本地订单，并按成交记录补出成交与持仓。

## 为什么每次都从上游事实重建订单

同步不是把两个数量相加：上游才是事实来源。每次同步都用「上游订单 + 该订单的全部
成交」重新算出本地订单的成交数量与成交金额，再按上游状态收敛。这样重复同步不会把
同一笔成交加两次，也不会因为上一次同步中断而留下半张单。

成交金额只从成交记录累加。上游订单本身不带成交金额，拿订单数量乘一个价格会把未知
成本编成看起来有效的数字；没有成交记录时 `filled_cost` 保持 0，成交均价返回 `None`。

持仓直接采用上游快照：上游明确返回空持仓就清空本地持仓；这次没有取持仓时保留本地
持仓，不把「没查」当成「没有」。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from app.core import Fill, ValidationError
from app.execution.model import ExecutionState, SyncResult, VenueSnapshot
from app.execution.orders import (
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_FILLED,
    STATUS_OPEN,
    STATUS_PARTIALLY_FILLED,
    STATUS_PENDING,
    TERMINAL_STATUSES,
    Order,
    accept,
    apply_fill,
    cancel,
    fail,
    require_transition,
)

__all__ = ["sync_state"]

ZERO = Decimal(0)


def sync_state(state: ExecutionState, venue: VenueSnapshot, *, now: datetime) -> SyncResult:
    """把本地状态与一份上游快照对齐，返回新的本地状态与本次变化。"""

    if now.tzinfo is None:
        raise ValidationError("同步时间必须带时区")
    venue_orders = _unique_venue_orders(tuple(_local_key(order) for order in venue.orders))
    fills = _merge_fills(state.fills, venue.fills)
    by_order_id = {order.order_id: order for order in venue_orders if order.order_id}
    by_client_id = {order.client_order_id: order for order in venue_orders}

    orders: list[Order] = []
    added: list[str] = []
    updated: list[str] = []
    failed: list[str] = []
    consumed: set[str] = set()

    for local in state.orders:
        match = _match(local, by_order_id, by_client_id)
        if match is None:
            if local.status in TERMINAL_STATUSES:
                orders.append(local)
            else:
                orders.append(fail(local, now=now))
                failed.append(local.client_order_id)
            continue
        consumed.add(match.client_order_id)
        rebuilt = _rebuild(local, match, fills, now=now)
        orders.append(rebuilt)
        if rebuilt != local:
            updated.append(local.client_order_id)

    for venue_order in venue_orders:
        if venue_order.client_order_id in consumed:
            continue
        orders.append(_rebuild(None, venue_order, fills, now=now))
        added.append(venue_order.client_order_id)

    positions = state.positions if venue.positions is None else venue.positions
    new_state = ExecutionState(
        orders=tuple(sorted(orders, key=lambda order: (order.created_at, order.client_order_id))),
        fills=fills,
        positions=positions,
    )
    return SyncResult(
        state=new_state,
        added_client_order_ids=tuple(added),
        updated_client_order_ids=tuple(updated),
        failed_client_order_ids=tuple(failed),
    )


def _match(
    local: Order,
    by_order_id: dict[str, Order],
    by_client_id: dict[str, Order],
) -> Order | None:
    """先按上游订单号匹配，再按幂等键匹配。

    本地 `pending` 订单还没拿到上游订单号，只能靠幂等键；已经拿到订单号的订单优先
    按订单号匹配，避免同一个键被错误地配到另一张单上。
    """

    if local.order_id:
        match = by_order_id.get(local.order_id)
        if match is not None:
            return match
    return by_client_id.get(local.client_order_id)


def _rebuild(
    local: Order | None,
    venue: Order,
    fills: tuple[Fill, ...],
    *,
    now: datetime,
) -> Order:
    """用上游订单与全部成交重建本地订单。

    起点是 `pending`，收到上游订单号才推进到 `open`；有成交时逐笔累加。这样重建过程
    本身就是状态机的一次完整推演，不靠直接写状态绕过转移校验。
    """

    if local is not None:
        _require_same_order(local, venue)
    order_id = venue.order_id or (local.order_id if local is not None else "")
    base = Order(
        client_order_id=venue.client_order_id,
        inst_id=venue.inst_id,
        side=venue.side,
        order_type=venue.order_type,
        qty=venue.qty,
        price=venue.price,
        created_at=local.created_at if local is not None else venue.created_at,
        updated_at=now,
        order_id=order_id,
        pos_side=local.pos_side if local is not None else venue.pos_side,
        reduce_only=local.reduce_only if local is not None else venue.reduce_only,
    )
    order_fills = _fills_for(venue, local, fills)
    if order_id:
        base = accept(base, order_id, now=now)
    elif order_fills:
        raise ValidationError(f"上游订单 {venue.client_order_id} 有成交却没有订单号")
    for fill in order_fills:
        base = apply_fill(base, fill, now=now)
    return _align(base, venue, now=now)


def _require_same_order(local: Order, venue: Order) -> None:
    """同一个订单号或幂等键不能对应两个不同的意图。"""

    if local.inst_id != venue.inst_id:
        raise ValidationError(
            f"本地订单 {local.client_order_id} 的标的 {local.inst_id} 与上游 {venue.inst_id} 不一致"
        )
    if local.side != venue.side:
        raise ValidationError(
            f"本地订单 {local.client_order_id} 的方向 {local.side} 与上游 {venue.side} 不一致"
        )
    if local.qty != venue.qty:
        raise ValidationError(
            f"本地订单 {local.client_order_id} 的数量 {local.qty} 与上游 {venue.qty} 不一致"
        )


def _align(order: Order, venue: Order, *, now: datetime) -> Order:
    """把重建后的订单收敛到上游状态。

    成交记录可能不完整：上游回报已成交数量时，即使成交明细还没返回，也要把数量与
    状态对齐；成交金额保持已知部分，不拿订单价格伪造。这种情况下成交均价只由已知
    成交算出、分母却是上游的全部成交量，它不是可用的加权均价，读的时候不能拿它当
    成交价。
    """

    if venue.status == STATUS_CANCELLED:
        return order if order.status in TERMINAL_STATUSES else cancel(order, now=now)
    if venue.status == STATUS_FAILED:
        return order if order.status in TERMINAL_STATUSES else fail(order, now=now)
    if venue.status == STATUS_PENDING:
        return order
    if venue.status == STATUS_OPEN:
        if order.status == STATUS_PENDING and order.order_id:
            return accept(order, order.order_id, now=now)
        target = ZERO
    elif venue.status == STATUS_PARTIALLY_FILLED:
        target = venue.filled_qty
    elif venue.status == STATUS_FILLED:
        target = order.qty
    else:
        raise ValidationError(f"未知的上游订单状态 {venue.status!r}")
    # 上游快照可能晚于已知成交：不把已经落账的成交量往回改。
    target = max(target, order.filled_qty)
    if target == order.filled_qty:
        return order
    target_status = STATUS_FILLED if target == order.qty else STATUS_PARTIALLY_FILLED
    if order.status == STATUS_PENDING:
        order = accept(order, venue.order_id, now=now)
    require_transition(order.status, target_status)
    return replace(order, status=target_status, filled_qty=target, updated_at=now)


def _fills_for(
    venue: Order,
    local: Order | None,
    fills: tuple[Fill, ...],
) -> tuple[Fill, ...]:
    """取属于这张订单的成交；本地与上游订单号都参与匹配。"""

    order_ids = {venue.order_id, local.order_id if local is not None else ""} - {""}
    if not order_ids:
        return ()
    return tuple(fill for fill in fills if fill.order_id in order_ids)


def _unique_venue_orders(orders: tuple[Order, ...]) -> tuple[Order, ...]:
    """上游快照里同一张订单只能出现一次，否则同步会重复记账。"""

    seen_client: set[str] = set()
    seen_order: set[str] = set()
    for order in orders:
        if order.client_order_id in seen_client:
            raise ValidationError(f"上游订单快照里 client_order_id 重复:{order.client_order_id}")
        seen_client.add(order.client_order_id)
        if order.order_id:
            if order.order_id in seen_order:
                raise ValidationError(f"上游订单快照里订单号重复:{order.order_id}")
            seen_order.add(order.order_id)
    return tuple(orders)


def _local_key(order: Order) -> Order:
    """给没有幂等键的上游订单补一个本地键。

    交易所在本项目之外下的单没有 `clOrdId`，但同步仍要把它补进本地订单表。用订单号
    派生 `x<订单号>`：稳定、可重复，且与计划派生的键不会混淆。两者都没有时这张单
    无法被本地识别，直接报错而不是让一条空键订单在本地互相覆盖。
    """

    if order.client_order_id:
        return order
    if not order.order_id:
        raise ValidationError("上游订单既没有幂等键也没有订单号, 无法在本地登记")
    return replace(order, client_order_id=f"x{order.order_id}")


def _merge_fills(existing: tuple[Fill, ...], incoming: tuple[Fill, ...]) -> tuple[Fill, ...]:
    """合并成交并按 `fill_id` 去重；没有 `fill_id` 时用完整字段做键。"""

    merged: dict[str, Fill] = {}
    for fill in (*existing, *incoming):
        key = fill.fill_id or "|".join(
            (
                fill.order_id,
                fill.inst_id,
                fill.side,
                format(fill.qty, "f"),
                format(fill.price, "f"),
                fill.ts.isoformat(),
            )
        )
        merged[key] = fill
    return tuple(sorted(merged.values(), key=lambda fill: (fill.ts, fill.fill_id)))

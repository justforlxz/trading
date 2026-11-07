"""故障恢复：重启 / 断线后接管或安全撤销未完成订单。

规则（顺序即优先级）：

1. paper 模式先用持久化成交重建模拟交易所，避免「重启即失真」。
2. 本地 `pending` / `submitted` / `partial` 订单逐笔向交易所求证：
   * 交易所仍有该单 → 拉成交、推进状态机（接管）。
   * 交易所查无此单 → `pending` 记 `rejected`（从未发出），
     其余记 `canceled`（已发出但已消失），绝不重发。
3. 恢复结束跑一次对账，把无法自动判定的事实落成差异记录。

成交落库以 `(order_id, fill_id)` 唯一键幂等，因此重复恢复不会重复计仓。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution import models, paper, reconcile, service
from app.execution.core import orders as order_core
from app.ports.private import ExchangeFill, OrderRequest, PrivateTradingSource

ZERO = Decimal("0")
OPEN_STATES = ("pending", "submitted", "partial")


@asynccontextmanager
async def _active(
    session: AsyncSession,
    *,
    mode: str,
    inst_id: str | None,
    source: PrivateTradingSource | None,
):
    if source is not None:
        yield source
        return
    async with service.source_for(session, mode, inst_id) as active:
        yield active


async def _rehydrate_paper(session: AsyncSession) -> int:
    rows = list(
        (
            await session.execute(
                select(models.Order)
                .where(models.Order.mode == service.MODE_PAPER)
                .order_by(models.Order.id)
            )
        ).scalars()
    )
    fills_by_order: dict[int, list[models.Fill]] = {row.id: [] for row in rows}
    if fills_by_order:
        for fill in (
            await session.execute(
                select(models.Fill)
                .where(models.Fill.order_id.in_(tuple(fills_by_order)))
                .order_by(models.Fill.id)
            )
        ).scalars():
            fills_by_order[fill.order_id].append(fill)

    entries: list[tuple[OrderRequest, Decimal, str, list[ExchangeFill]]] = []
    for row in rows:
        fills = fills_by_order[row.id]
        if not fills and (row.price is None or row.price <= ZERO):
            # 无成交、无价格的僵尸单：不进撮合器（否则会造出 0 价成交），
            # 交给下方恢复循环按「交易所查无此单」安全撤销。
            continue
        request = OrderRequest(
            inst_id=row.inst_id,
            side=row.side,
            position_side=row.position_side,
            order_type=row.order_type,
            quantity=row.quantity,
            price=row.price,
            client_order_id=row.client_order_id,
            reduce_only=row.reduce_only,
        )
        price = row.price or (fills[0].price if fills else row.average_price or ZERO)
        entries.append(
            (
                request,
                price,
                row.state,
                [
                    ExchangeFill(
                        fill_id=fill.fill_id,
                        client_order_id=row.client_order_id,
                        exchange_order_id=row.exchange_order_id or f"paper-{row.client_order_id}",
                        inst_id=fill.inst_id,
                        side=fill.side,
                        position_side=fill.position_side,
                        quantity=fill.quantity,
                        price=fill.price,
                        fee=fill.fee,
                        fee_currency="USDT",
                        filled_at=fill.filled_at,
                    )
                    for fill in fills
                ],
            )
        )
    paper.get_paper_source().rehydrate(entries)
    return len(entries)


async def run(
    session: AsyncSession,
    *,
    source: PrivateTradingSource | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """恢复全部未完成订单并顺带对账；返回可核对的计数。"""

    moment = now or datetime.now(tz=UTC)
    mode = service.resolve_mode()
    rehydrated = 0
    if source is None and mode == service.MODE_PAPER:
        rehydrated = await _rehydrate_paper(session)

    open_rows = list(
        (
            await session.execute(
                select(models.Order)
                .where(models.Order.state.in_(OPEN_STATES))
                .order_by(models.Order.id)
            )
        ).scalars()
    )

    reattached = 0
    rejected = 0
    canceled = 0
    for order in open_rows:
        async with _active(
            session, mode=order.mode, inst_id=order.inst_id, source=source
        ) as active:
            snapshot = await active.fetch_order(
                inst_id=order.inst_id,
                client_order_id=order.client_order_id,
                exchange_order_id=order.exchange_order_id,
            )
            if snapshot is None:
                if order.state == "pending":
                    order.state = order_core.ensure_transition(order.state, "rejected")
                    order.reject_reason = "recovered_unsent"
                    rejected += 1
                else:
                    order.state = order_core.ensure_transition(order.state, "canceled")
                    order.reject_reason = "recovered_missing_on_exchange"
                    canceled += 1
                order.closed_at = moment
                await session.commit()
                continue
            await service.sync_order(session, order, active)
            reattached += 1

    async with _active(session, mode=mode, inst_id=None, source=source) as active:
        reconcile_result = await reconcile.run(session, source=active, now=moment)

    return {
        "mode": mode,
        "rehydrated_orders": rehydrated,
        "open_orders": len(open_rows),
        "reattached": reattached,
        "rejected_unsent": rejected,
        "canceled_missing": canceled,
        "reconcile": reconcile_result,
    }


__all__ = ["OPEN_STATES", "run"]

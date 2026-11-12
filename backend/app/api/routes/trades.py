"""Trades 只读端点：交易历史聚合。

端点只做两件事：取执行快照、把 journal 读模型投影成契约模型。策略与回测的读取
在 `app.journal`，执行事实来自装配根挂在应用上的最新快照，端点自己不写任何表。

执行快照由 `app.main:create_app` 初始化，并在执行编排完成一次下单或同步后替换。
还没有任何执行事实时返回空快照，页面显示空状态，不会编造业务数值。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.mapping import decimal_str
from app.api.schemas import (
    JournalCashFlow,
    JournalEntry,
    JournalFill,
    JournalListResponse,
    JournalOrder,
    JournalPosition,
    JournalReturnPoint,
    JournalSignal,
    StrategyJournalSummary,
)
from app.core import Fill
from app.execution import Order
from app.journal import ExecutionSnapshot, JournalView, load_journal

__all__ = ["trades_router"]

trades_router = APIRouter(tags=["trades"])


@trades_router.get("/journal", response_model=JournalListResponse)
def get_journal_history(request: Request) -> JournalListResponse:
    """交易历史：策略配置与版本、回测预期、实际成交、持仓、订单、信号与日志。"""

    snapshot: ExecutionSnapshot = request.app.state.execution_snapshot
    view = load_journal(snapshot=snapshot)
    assert view is not None
    return _journal_response(view)


def _journal_response(view: JournalView) -> JournalListResponse:
    owners = _order_owners(view)
    order_keys = {order.order_id: order.client_order_id for order in view.orders}
    return JournalListResponse(
        mode=view.mode,
        strategies=[_strategy(item) for item in view.strategies],
        positions=[_position(item, mode=view.mode) for item in view.positions],
        orders=[_order(item, view.mode, owners.get(item.client_order_id)) for item in view.orders],
        fills=[
            _fill(item, view.mode, owners.get(order_keys.get(item.order_id, "")))
            for item in view.fills
        ],
        signals=[_signal(item) for item in view.signals],
        items=[_entry(item) for item in view.entries],
        total=len(view.entries),
    )


def _strategy(item) -> StrategyJournalSummary:
    return StrategyJournalSummary(
        instance_id=item.instance_id,
        strategy_id=item.strategy_id,
        strategy_version=item.strategy_version,
        name=item.name,
        bar=item.bar,
        lifecycle_status=item.lifecycle_status,
        execution_mode=item.execution_mode,
        params=dict(item.params),
        inst_ids=list(item.inst_ids),
        expected_return=(
            None if item.expected_return is None else decimal_str(item.expected_return)
        ),
        expected_source=item.expected_source,
        actual_return=decimal_str(item.actual_return),
        actual_source=item.actual_source,
        net_cash_flow=decimal_str(item.net_cash_flow),
        fill_count=item.fill_count,
        cash_flow=[
            JournalCashFlow(at=point.at, inst_id=point.inst_id, amount=decimal_str(point.amount))
            for point in item.cash_flow
        ],
        actual_curve=[
            JournalReturnPoint(at=point.at, value=decimal_str(point.value))
            for point in item.actual_curve
        ],
    )


def _position(item, *, mode: str) -> JournalPosition:
    return JournalPosition(
        product_key=item.product_key,
        inst_type=item.inst_type,
        side=item.side,
        qty=decimal_str(item.qty),
        avg_cost=decimal_str(item.avg_cost),
        leverage=None if item.leverage is None else decimal_str(item.leverage),
        liquidation_price=None if item.liq_price is None else decimal_str(item.liq_price),
        mode=mode,
    )


def _order(item: Order, mode: str, owner: str | None) -> JournalOrder:
    average = None if item.filled_qty <= 0 else decimal_str(item.filled_cost / item.filled_qty)
    return JournalOrder(
        client_order_id=item.client_order_id,
        order_id=item.order_id,
        inst_id=item.inst_id,
        side=item.side,
        order_type=item.order_type,
        price=None if item.price is None else decimal_str(item.price),
        qty=decimal_str(item.qty),
        filled_qty=decimal_str(item.filled_qty),
        avg_fill_price=average,
        status=_order_status(item.status),
        reduce_only=item.reduce_only,
        mode=mode,
        strategy_instance_id=owner,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _fill(item: Fill, mode: str, owner: str | None) -> JournalFill:
    return JournalFill(
        fill_id=item.fill_id,
        order_id=item.order_id,
        inst_id=item.inst_id,
        side=item.side,
        price=decimal_str(item.price),
        qty=decimal_str(item.qty),
        fee=decimal_str(item.fee.amount),
        fee_currency=item.fee.currency,
        filled_at=item.ts,
        strategy_instance_id=owner,
    )


def _signal(item) -> JournalSignal:
    return JournalSignal(
        signal_id=item.signal_id,
        instance_id=item.instance_id,
        inst_id=item.inst_id,
        inst_type=item.inst_type,
        side=item.side,
        strength=float(item.strength),
        price=None if item.price is None else decimal_str(item.price),
        reason=item.reason,
        generated_at=item.generated_at,
        target_weight=(None if item.target_weight is None else decimal_str(item.target_weight)),
    )


def _entry(item) -> JournalEntry:
    return JournalEntry(
        entry_id=item.entry_id,
        category=item.category,
        message=item.message,
        inst_id=item.inst_id,
        created_at=item.created_at,
    )


def _order_owners(view: JournalView) -> dict[str, str]:
    return {
        order.client_order_id: owner
        for order in view.orders
        for owner in [view.order_owners.get(order.client_order_id)]
        if owner is not None
    }


def _order_status(status: str) -> str:
    """执行域的 `failed` 在对外契约里叫 `rejected`；其余状态同名直传。"""

    return "rejected" if status == "failed" else status

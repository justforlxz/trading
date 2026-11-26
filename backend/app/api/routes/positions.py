"""持仓与账户端点：只做 HTTP 映射，业务口径在 `app.positions` 里。

OKX 端点只读：同步只调用账户与持仓查询，不提供任何下单、撤单或平仓入口。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException

from app.api.mapping import decimal_str
from app.api.schemas.positions import (
    AccountSummaryResponse,
    AccountSyncResponse,
    CurvePointItem,
    EquityCurveResponse,
    ExchangePositionItem,
    ExchangePositionsResponse,
    ManualPositionCreateRequest,
    ManualPositionItem,
    ManualPositionListResponse,
    ManualPositionUpdateRequest,
    ManualTradeItem,
    ManualTradeListResponse,
    ManualTradeRequest,
    MergedPositionItem,
    MergedPositionsResponse,
    OrderHistoryItem,
    OrderHistoryResponse,
    OrderScope,
    PositionCardItem,
    PositionCardsResponse,
)
from app.core import OrderRecord
from app.dashboard import MergedPosition, load_merged_positions
from app.positions import (
    AccountSyncView,
    AccountView,
    CurvePoint,
    ExchangePositionView,
    ManualPositionView,
    ManualTradeView,
    PositionCard,
    account_summary,
    add_manual_trade,
    create_manual_position,
    delete_manual_position,
    equity_curve,
    exchange_positions,
    instrument_order_history,
    list_manual_positions,
    list_manual_trades,
    position_cards,
    sync_account,
    update_manual_position,
)

__all__ = ["positions_router"]

positions_router = APIRouter(tags=["positions"])


@positions_router.get("/account/summary", response_model=AccountSummaryResponse)
def get_account_summary() -> AccountSummaryResponse:
    """最近一条账户快照；没有配置或没有快照时返回 200 与明确状态。"""

    return _account(account_summary())


@positions_router.post("/account/sync", response_model=AccountSyncResponse)
def sync_account_snapshot() -> AccountSyncResponse:
    """采集一次 OKX 只读快照；上游故障返回 502，且不写半套数据。"""

    return _sync(sync_account())


@positions_router.get("/account/equity-curve", response_model=EquityCurveResponse)
def get_account_equity_curve(
    range: Literal["1d", "1w", "1m", "6m", "1y"] = "1d",
) -> EquityCurveResponse:
    """按区间读权益曲线；覆盖不足时 `available=false` 且不给点，不画假线。"""

    view = equity_curve(range)
    return EquityCurveResponse(
        range=view.range,
        available=view.available,
        change_pct=_optional_text(view.change_pct),
        points=[_curve_point(point) for point in view.points],
        first_snapshot_at=view.first_snapshot_at,
        last_snapshot_at=view.last_snapshot_at,
    )


@positions_router.get("/positions/cards", response_model=PositionCardsResponse)
def get_position_cards(
    range: Literal["1d", "1w", "1m", "6m", "1y"] = "1d",
) -> PositionCardsResponse:
    """持仓卡片：已按未实现盈亏绝对值降序，含每条持仓的盈亏曲线与止损三态。

    名义价值低于配置阈值的尘埃不在 `items` 里，条数由 `hidden_dust_count` 给出。
    """

    view = position_cards(range)
    return PositionCardsResponse(
        as_of=view.as_of,
        status=view.status,  # type: ignore[arg-type]
        items=[_position_card(card) for card in view.items],
        hidden_dust_count=view.hidden_dust_count,
    )


@positions_router.get("/positions/{inst_id}/orders", response_model=OrderHistoryResponse)
def get_instrument_orders(
    inst_id: str,
    scope: OrderScope = "all",
) -> OrderHistoryResponse:
    """单标的订单历史：近 7 天与归档合并，按时间倒序。

    上游不可用时返回 502 —— 空列表代表「确实没有订单」，不能用来表示「没查到」。
    """

    records = instrument_order_history(inst_id)
    items = [
        _order_history_item(record)
        for record in records
        if scope == "all" or (scope == "open") == record.is_open
    ]
    return OrderHistoryResponse(inst_id=inst_id, scope=scope, window_days=90, items=items)


@positions_router.get("/positions/exchange", response_model=ExchangePositionsResponse)
def get_exchange_positions() -> ExchangePositionsResponse:
    """最近一次同步的交易所持仓，`as_of` 与该次账户快照相同；标的未同步时返回 503。"""

    view = exchange_positions(require_mapped=True)
    return ExchangePositionsResponse(
        as_of=view.as_of,
        status=view.status,  # type: ignore[arg-type]
        items=[_exchange_position(item) for item in view.items],
    )


@positions_router.get("/positions", response_model=MergedPositionsResponse)
def get_positions(
    source: Literal["exchange", "manual"] | None = None,
) -> MergedPositionsResponse:
    """OKX 与手动持仓的合并视图；`source` 可按来源过滤。"""

    view = load_merged_positions()
    items = (
        view.items
        if source is None
        else tuple(item for item in view.items if item.source == source)
    )
    return MergedPositionsResponse(
        as_of=view.as_of,
        exchange_status=view.exchange_status,  # type: ignore[arg-type]
        items=[_merged_position(item) for item in items],
    )


@positions_router.get("/manual-positions", response_model=ManualPositionListResponse)
def get_manual_positions() -> ManualPositionListResponse:
    items = [_manual_position(row) for row in list_manual_positions()]
    return ManualPositionListResponse(items=items)


@positions_router.post(
    "/manual-positions",
    response_model=ManualPositionItem,
    status_code=201,
)
def create_manual_position_endpoint(
    payload: ManualPositionCreateRequest,
) -> ManualPositionItem:
    """创建手动持仓并写入一条 `open` 流水；重复幂等键返回原持仓。"""

    view = create_manual_position(
        inst_id=payload.inst_id,
        side=payload.side,
        quantity=Decimal(payload.quantity),
        avg_cost=Decimal(payload.avg_cost),
        stop_px=_optional_decimal(payload.stop_px),
        leverage=_optional_decimal(payload.leverage),
        note=payload.note,
        idempotency_key=payload.idempotency_key,
    )
    return _manual_position(view)


@positions_router.patch(
    "/manual-positions/{position_id}",
    response_model=ManualPositionItem,
)
def update_manual_position_endpoint(
    position_id: str,
    payload: ManualPositionUpdateRequest,
) -> ManualPositionItem:
    """只改止损价、杠杆与备注；数量和成本只能通过流水改变。"""

    view = update_manual_position(
        position_id,
        changes=_manual_position_changes(payload),
    )
    if view is None:
        raise HTTPException(status_code=404, detail=f"未找到手动持仓 {position_id}")
    return _manual_position(view)


@positions_router.post(
    "/manual-positions/{position_id}/trades",
    response_model=ManualTradeItem,
    status_code=201,
)
def add_manual_trade_endpoint(
    position_id: str,
    payload: ManualTradeRequest,
) -> ManualTradeItem:
    """写入手动流水；数量和成本在同一事务内更新，重复幂等键返回原流水。"""

    view = add_manual_trade(
        position_id,
        action=payload.action,
        quantity=Decimal(payload.quantity),
        price=Decimal(payload.price),
        fee=Decimal(payload.fee),
        occurred_at=payload.occurred_at,
        note=payload.note,
        idempotency_key=payload.idempotency_key,
    )
    if view is None:
        raise HTTPException(status_code=404, detail=f"未找到手动持仓 {position_id}")
    return _manual_trade(view)


@positions_router.get(
    "/manual-positions/{position_id}/trades",
    response_model=ManualTradeListResponse,
)
def get_manual_trades(position_id: str) -> ManualTradeListResponse:
    """按发生时刻倒序返回流水，带每条流水之后的持仓数量和成本。"""

    views = list_manual_trades(position_id)
    if views is None:
        raise HTTPException(status_code=404, detail=f"未找到手动持仓 {position_id}")
    return ManualTradeListResponse(items=[_manual_trade(row) for row in views])


@positions_router.delete("/manual-positions/{position_id}", status_code=204)
def delete_manual_position_endpoint(position_id: str) -> None:
    """只允许删除没有任何流水的持仓；已有流水返回 409。"""

    deleted = delete_manual_position(position_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail=f"未找到手动持仓 {position_id}")


def _account(view: AccountView) -> AccountSummaryResponse:
    return AccountSummaryResponse(
        status=view.status,  # type: ignore[arg-type]
        account_id=view.account_id,
        currency=view.currency,
        equity=_optional_text(view.equity),
        available_equity=_optional_text(view.available_equity),
        cash_balance=_optional_text(view.cash_balance),
        unrealized_pnl=_optional_text(view.unrealized_pnl),
        used_margin=_optional_text(view.used_margin),
        available_margin=_optional_text(view.available_margin),
        margin_usage_pct=_optional_text(view.margin_usage_pct),
        day_pnl=_optional_text(view.day_pnl),
        position_notional=_optional_text(view.position_notional),
        position_notional_at=view.position_notional_at,
        gross_notional=_optional_text(view.gross_notional),
        net_notional=_optional_text(view.net_notional),
        notional_status=view.notional_status,  # type: ignore[arg-type]
        margin_used=_optional_text(view.margin_used),
        margin_usage_floor=view.margin_usage_floor,
        captured_at=view.captured_at,
        source=view.source,
    )


def _sync(view: AccountSyncView) -> AccountSyncResponse:
    account = _account(view.summary)
    return AccountSyncResponse(
        **account.model_dump(),
        positions_synced=view.positions_synced,
    )


def _exchange_position(view: ExchangePositionView) -> ExchangePositionItem:
    return ExchangePositionItem(
        pos_id=view.pos_id,
        inst_id=view.inst_id,
        display_symbol=view.display_symbol,
        name=view.name,
        asset_class=view.asset_class,
        pos_side=view.pos_side,  # type: ignore[arg-type]
        size=decimal_str(view.size),
        avg_px=decimal_str(view.avg_px),
        mark_px=_optional_text(view.mark_px),
        upl=_optional_text(view.upl),
        upl_ratio=_optional_text(view.upl_ratio),
        lever=_optional_text(view.lever),
        mgn_mode=view.mgn_mode,
        liq_px=_optional_text(view.liq_px),
        margin=_optional_text(view.margin),
    )


def _curve_point(point: CurvePoint) -> CurvePointItem:
    return CurvePointItem(at=point.at, value=decimal_str(point.value))


def _position_card(card: PositionCard) -> PositionCardItem:
    return PositionCardItem(
        pos_id=card.pos_id,
        inst_id=card.inst_id,
        display_symbol=card.display_symbol,
        name=card.name,
        asset_class=card.asset_class,
        inst_type=card.inst_type,
        pos_side=card.pos_side,  # type: ignore[arg-type]
        size=decimal_str(card.size),
        avg_px=decimal_str(card.avg_px),
        mark_px=_optional_text(card.mark_px),
        mark_px_source=card.mark_px_source,
        mark_px_at=card.mark_px_at,
        upl=_optional_text(card.upl),
        upl_ratio=_optional_text(card.upl_ratio),
        lever=_optional_text(card.lever),
        mgn_mode=card.mgn_mode,
        liq_px=_optional_text(card.liq_px),
        margin=_optional_text(card.margin),
        notional=_optional_text(card.notional),
        weight_pct=_optional_text(card.weight_pct),
        stop_supported=card.stop_supported,
        stop_status=card.stop_status,  # type: ignore[arg-type]
        stop_px=_optional_text(card.stop_px),
        stop_distance_pct=_optional_text(card.stop_distance_pct),
        upl_curve=[_curve_point(point) for point in card.upl_curve],
    )


def _order_history_item(record: OrderRecord) -> OrderHistoryItem:
    return OrderHistoryItem(
        order_id=record.order_id,
        side="sell" if record.side == "sell" else "buy",
        order_type=record.order_type,
        price=_optional_text(record.price),
        avg_px=_optional_text(record.avg_px),
        qty=decimal_str(record.qty),
        filled_qty=decimal_str(record.filled_qty),
        pnl=_optional_text(record.pnl),
        fee=_optional_text(record.fee),
        status=record.status,
        is_open=record.is_open,
        ts=record.ts,
    )


def _merged_position(item: MergedPosition) -> MergedPositionItem:
    return MergedPositionItem(
        position_ref=item.position_ref,
        source=item.source,  # type: ignore[arg-type]
        inst_id=item.inst_id,
        display_symbol=item.display_symbol,
        name=item.name,
        asset_class=item.asset_class,
        side=item.side,  # type: ignore[arg-type]
        size=decimal_str(item.size),
        avg_px=decimal_str(item.avg_px),
        mark_px=_optional_text(item.mark_px),
        upl=_optional_text(item.upl),
        upl_ratio=_optional_text(item.upl_ratio),
        lever=_optional_text(item.lever),
        mgn_mode=item.mgn_mode,
        liq_px=_optional_text(item.liq_px),
        margin=_optional_text(item.margin),
        notional=_optional_text(item.notional),
        stop_px=_optional_text(item.stop_px),
        stop_distance_pct=_optional_text(item.stop_distance_pct),
        price_status=item.price_status,  # type: ignore[arg-type]
        updated_at=item.updated_at,
    )


def _manual_position(view: ManualPositionView) -> ManualPositionItem:
    return ManualPositionItem(
        id=view.id,
        inst_id=view.inst_id,
        display_symbol=view.display_symbol,
        name=view.name,
        asset_class=view.asset_class,
        side=view.side,  # type: ignore[arg-type]
        quantity=decimal_str(view.quantity),
        avg_cost=decimal_str(view.avg_cost),
        stop_px=_optional_text(view.stop_px),
        leverage=_optional_text(view.leverage),
        status=view.status,  # type: ignore[arg-type]
        note=view.note,
        price=_optional_text(view.price),
        price_status=view.price_status,  # type: ignore[arg-type]
        price_source=view.price_source,  # type: ignore[arg-type]
        market_value=_optional_text(view.market_value),
        unrealized_pnl=_optional_text(view.unrealized_pnl),
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


def _manual_trade(view: ManualTradeView) -> ManualTradeItem:
    return ManualTradeItem(
        id=view.id,
        position_id=view.position_id,
        action=view.action,  # type: ignore[arg-type]
        quantity=decimal_str(view.quantity),
        price=decimal_str(view.price),
        fee=decimal_str(view.fee),
        realized_pnl=_optional_text(view.realized_pnl),
        position_quantity_after=decimal_str(view.position_quantity_after),
        position_avg_cost_after=decimal_str(view.position_avg_cost_after),
        position_status_after=view.position_status_after,  # type: ignore[arg-type]
        occurred_at=view.occurred_at,
        note=view.note,
        created_at=view.created_at,
    )


def _manual_position_changes(payload: ManualPositionUpdateRequest) -> dict[str, object]:
    changes: dict[str, object] = {}
    for name, value in payload.model_dump(exclude_unset=True).items():
        is_decimal = name in {"stop_px", "leverage"} and value is not None
        changes[name] = Decimal(value) if is_decimal else value
    return changes


def _optional_text(value: Decimal | None) -> str | None:
    return None if value is None else decimal_str(value)


def _optional_decimal(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)

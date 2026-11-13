"""自选域端点：条目、分组、价格提醒与相关标的。

端点只做入参校验与响应组装，行情口径与持久化都在 `app.watchlist` 里。
域层用 `None` / `False` 表示「不存在」，这一层再翻译成 404。
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.mapping import decimal_str, instrument_info
from app.api.schemas import (
    PriceAlert,
    PriceAlertRequest,
    RelatedInstrument,
    RelatedInstrumentsResponse,
    Signal,
    WatchlistAddRequest,
    WatchlistItem,
    WatchlistResponse,
    WatchlistStrategy,
    WatchlistUpdateRequest,
)
from app.journal import ExecutionSnapshot, RecordedSignal
from app.strategy import InstanceRecord, list_instances
from app.watchlist import (
    AlertSnapshot,
    RelatedCandidate,
    WatchlistEntry,
    add_item,
    clear_alert,
    list_entries,
    list_groups,
    move_item,
    related_instruments,
    remove_item,
    set_alert,
)

__all__ = ["watchlist_router"]

watchlist_router = APIRouter(tags=["watchlist"])


@watchlist_router.get("/watchlist")
def list_watchlist(request: Request) -> WatchlistResponse:
    """按加入顺序返回全部自选条目、分组名，以及关联策略与最近信号。

    策略与信号由本层从 `strategy` / `execution` 门面组合：`watchlist` 域本身不依赖
    这两个模块，列表行的行情口径仍由 `app.watchlist` 单独负责。
    """

    entries = list_entries()
    instances, _ = list_instances(limit=500)
    snapshot: ExecutionSnapshot = getattr(
        request.app.state, "execution_snapshot", ExecutionSnapshot()
    )
    strategies = _strategy_by_instrument(instances)
    signals = _latest_signals(snapshot.signals)
    instance_index = {item.instance_id: item for item in instances}
    return WatchlistResponse(
        items=[
            _item(
                entry,
                strategies.get(entry.instrument.symbol),
                signals.get(entry.instrument.symbol),
                instance_index,
            )
            for entry in entries
        ],
        groups=list_groups(),
    )


@watchlist_router.post("/watchlist", status_code=201)
def add_watchlist_item(payload: WatchlistAddRequest, request: Request) -> WatchlistItem:
    """把标的加入自选；标的必须已同步，且已有足够的日线可算行情。"""

    entry = add_item(payload.inst_id, payload.group)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"未找到标的 {payload.inst_id}")
    return _compose_one(request, entry)


@watchlist_router.get("/watchlist/{inst_id}/related")
def get_related_instruments(
    inst_id: str, window_days: int = Query(30, ge=5, le=180)
) -> RelatedInstrumentsResponse:
    """按窗口内日线相关性排序的关联标的；样本不足的候选不出现在结果里。"""

    candidates = related_instruments(inst_id, window_days)
    if candidates is None:
        raise HTTPException(status_code=404, detail=f"未找到标的 {inst_id}")
    return RelatedInstrumentsResponse(
        inst_id=inst_id,
        window_days=window_days,
        items=[_related(candidate, window_days) for candidate in candidates],
    )


@watchlist_router.put("/watchlist/{inst_id}/alert")
def put_price_alert(inst_id: str, payload: PriceAlertRequest) -> PriceAlert:
    """写入或覆盖价格提醒；标的必须已在自选里。"""

    snapshot = set_alert(
        inst_id,
        payload.direction,
        Decimal(payload.price),
        enabled=payload.enabled,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"自选里没有标的 {inst_id}")
    return _to_alert(snapshot)


@watchlist_router.delete("/watchlist/{inst_id}/alert", status_code=204)
def delete_price_alert(inst_id: str) -> None:
    """删除价格提醒；没有提醒时按不存在处理。"""

    if not clear_alert(inst_id):
        raise HTTPException(status_code=404, detail=f"标的 {inst_id} 没有价格提醒")


@watchlist_router.patch("/watchlist/{inst_id}")
def update_watchlist_item(
    inst_id: str, payload: WatchlistUpdateRequest, request: Request
) -> WatchlistItem:
    """把自选条目换到另一个分组；分组不存在时按需创建。"""

    entry = move_item(inst_id, payload.group)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"自选里没有标的 {inst_id}")
    return _compose_one(request, entry)


@watchlist_router.delete("/watchlist/{inst_id}", status_code=204)
def delete_watchlist_item(inst_id: str) -> None:
    """删除自选条目及其提醒；分组空了会一并清理。"""

    if not remove_item(inst_id):
        raise HTTPException(status_code=404, detail=f"自选里没有标的 {inst_id}")


def _item(
    entry: WatchlistEntry,
    strategy: InstanceRecord | None,
    signal: RecordedSignal | None,
    instances: dict[str, InstanceRecord],
) -> WatchlistItem:
    return WatchlistItem(
        instrument=instrument_info(entry.instrument),
        group=entry.group,
        last_price=decimal_str(entry.quote.last_price),
        change_pct_24h=decimal_str(entry.quote.change_pct_24h),
        volume_24h_quote=decimal_str(entry.quote.volume_24h_quote),
        strategy=None if strategy is None else _strategy(strategy),
        last_signal=_signal(signal, instances, entry.quote.last_price),
        alert=_alert(entry.alert),
    )


def _strategy_by_instrument(instances: tuple[InstanceRecord, ...]) -> dict[str, InstanceRecord]:
    """标的 → 最近建立且启用的策略实例；同一标的有多个时保留列表里的第一个。"""

    mapping: dict[str, InstanceRecord] = {}
    for instance in instances:
        if not instance.enabled:
            continue
        for inst_id in instance.inst_ids:
            mapping.setdefault(inst_id, instance)
    return mapping


def _compose_one(request: Request, entry: WatchlistEntry) -> WatchlistItem:
    instances, _ = list_instances(limit=500)
    snapshot: ExecutionSnapshot = getattr(
        request.app.state, "execution_snapshot", ExecutionSnapshot()
    )
    return _item(
        entry,
        _strategy_by_instrument(instances).get(entry.instrument.symbol),
        _latest_signals(snapshot.signals).get(entry.instrument.symbol),
        {item.instance_id: item for item in instances},
    )


def _latest_signals(
    signals: tuple[RecordedSignal, ...],
) -> dict[str, RecordedSignal]:
    """标的 → 最近一条信号；时刻相同时保留先出现的一条，结果稳定。"""

    latest: dict[str, RecordedSignal] = {}
    for signal in signals:
        current = latest.get(signal.inst_id)
        if current is None or signal.generated_at > current.generated_at:
            latest[signal.inst_id] = signal
    return latest


def _strategy(record: InstanceRecord) -> WatchlistStrategy:
    return WatchlistStrategy(
        instance_id=record.instance_id,
        name=record.name,
        status=record.lifecycle_status,
        execution_mode=record.execution_mode,
        enabled=record.enabled,
    )


def _signal(
    record: RecordedSignal | None,
    instances: dict[str, InstanceRecord],
    fallback_price: Decimal,
) -> Signal | None:
    """执行事实 → 契约信号；策略实例缺失时无法确定周期，宁可不显示也不编造。"""

    if record is None:
        return None
    instance = instances.get(record.instance_id)
    if instance is None:
        return None
    return Signal(
        signal_id=record.signal_id,
        strategy_instance_id=record.instance_id,
        inst_id=record.inst_id,
        inst_type=record.inst_type,
        action="BUY" if record.side == "long" else "SELL",
        bar=instance.bar,
        price=decimal_str(record.price if record.price is not None else fallback_price),
        reason=record.reason,
        generated_at=record.generated_at,
        target_weight=(None if record.target_weight is None else decimal_str(record.target_weight)),
    )


def _alert(snapshot: AlertSnapshot | None) -> PriceAlert | None:
    return None if snapshot is None else _to_alert(snapshot)


def _to_alert(snapshot: AlertSnapshot) -> PriceAlert:
    return PriceAlert(
        inst_id=snapshot.inst_id,
        direction=snapshot.direction,
        price=decimal_str(snapshot.price),
        enabled=snapshot.enabled,
        triggered_at=snapshot.triggered_at,
    )


def _related(candidate: RelatedCandidate, window_days: int) -> RelatedInstrument:
    return RelatedInstrument(
        inst_id=candidate.inst_id,
        product_key=candidate.product_key,
        asset_type=candidate.asset_type,
        correlation=decimal_str(candidate.correlation),
        window_days=window_days,
    )

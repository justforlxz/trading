"""对账：本地虚拟持仓与未完成订单 vs 交易所事实。

原则：

* **只记录差异，不改本地数据**。差异必须由人确认后通过
  `POST /execution/reconcile/diffs/{id}/resolve` 结案。
* 同一差异（kind + 标的 + 方向 + 引用）只保留一条 open 记录，重复对账不叠加。
* 存在 open 差异时真实下单被拒绝（见 `execution.gate`）。
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution import models
from app.execution.core import positions as position_core
from app.execution.errors import ExecutionError
from app.ports.private import ExchangePosition, PrivateTradingSource

ZERO = Decimal("0")
OPEN = "open"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def serialize_diff(diff: models.ReconcileDiff) -> dict[str, Any]:
    return {
        "id": diff.id,
        "kind": diff.kind,
        "strategy_id": diff.strategy_id,
        "instrument_id": diff.instrument_id,
        "inst_id": diff.inst_id,
        "position_side": diff.position_side,
        "reference": diff.reference,
        "local_value": _text(diff.local_value),
        "exchange_value": _text(diff.exchange_value),
        "detail": diff.detail,
        "status": diff.status,
        "detected_at": _iso(diff.detected_at),
        "resolved_at": _iso(diff.resolved_at),
        "resolved_by": diff.resolved_by,
        "note": diff.note,
        "resolve_attempts": diff.resolve_attempts,
    }


async def open_diff_count(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count(models.ReconcileDiff.id)).where(models.ReconcileDiff.status == OPEN)
        )
        or 0
    )


async def _upsert(
    session: AsyncSession,
    *,
    kind: str,
    inst_id: str,
    position_side: str,
    reference: str,
    instrument_id: int | None = None,
    strategy_id: int | None = None,
    local_value: Decimal | None = None,
    exchange_value: Decimal | None = None,
    detail: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> models.ReconcileDiff:
    """同键 open 差异复用原行并刷新观测值；不产生重复记录。"""

    existing = (
        await session.execute(
            select(models.ReconcileDiff).where(
                models.ReconcileDiff.status == OPEN,
                models.ReconcileDiff.kind == kind,
                models.ReconcileDiff.inst_id == inst_id,
                models.ReconcileDiff.position_side == position_side,
                models.ReconcileDiff.reference == reference,
            )
        )
    ).scalar_one_or_none()
    detected_at = now or datetime.now(tz=UTC)
    if existing is not None:
        existing.local_value = local_value
        existing.exchange_value = exchange_value
        existing.detail = detail or {}
        return existing

    diff = models.ReconcileDiff(
        kind=kind,
        strategy_id=strategy_id,
        instrument_id=instrument_id,
        inst_id=inst_id,
        position_side=position_side,
        reference=reference,
        local_value=local_value,
        exchange_value=exchange_value,
        detail=detail or {},
        status=OPEN,
        detected_at=detected_at,
    )
    session.add(diff)
    return diff


async def run(
    session: AsyncSession, *, source: PrivateTradingSource, now: datetime | None = None
) -> dict[str, Any]:
    """比对持仓与未完成订单，落差异记录后返回本次统计。"""

    local_rows = (
        await session.execute(
            select(
                models.Position.inst_id,
                models.Position.position_side,
                models.Position.instrument_id,
                func.sum(models.Position.quantity),
                func.max(models.Position.average_price),
            )
            .where(models.Position.quantity > ZERO)
            .group_by(
                models.Position.inst_id,
                models.Position.position_side,
                models.Position.instrument_id,
            )
        )
    ).all()
    local_positions = {
        (inst_id, position_side): (instrument_id, quantity, average)
        for inst_id, position_side, instrument_id, quantity, average in local_rows
    }

    try:
        exchange_rows = await source.fetch_positions()
    except position_core.PositionError as exc:
        # 交易源自身账本不可信：落一条差异并返回，对账绝不 500。
        await _upsert(
            session,
            kind="exchange_state_inconsistent",
            inst_id="",
            position_side="",
            reference="",
            detail={"error": str(exc)},
            now=now,
        )
        await session.commit()
        return {
            "checked_positions": 0,
            "checked_orders": 0,
            "diffs": 1,
            "open_diffs": await open_diff_count(session),
        }

    exchange_positions: dict[tuple[str, str], ExchangePosition] = {
        (item.inst_id, item.position_side): item for item in exchange_rows
    }

    detected = 0
    for key in sorted(set(local_positions) | set(exchange_positions)):
        inst_id, position_side = key
        local = local_positions.get(key)
        exchange = exchange_positions.get(key)
        local_quantity = local[1] if local else ZERO
        exchange_quantity = exchange.quantity if exchange else ZERO
        if local_quantity == exchange_quantity:
            continue
        detected += 1
        await _upsert(
            session,
            kind="position_mismatch",
            inst_id=inst_id,
            position_side=position_side,
            reference="",
            instrument_id=(local[0] if local else None),
            local_value=local_quantity,
            exchange_value=exchange_quantity,
            detail={
                "local_average_price": _text(local[2] if local else None),
                "exchange_average_price": _text(exchange.average_price if exchange else None),
            },
            now=now,
        )

    local_orders = {
        row.client_order_id: row
        for row in (
            await session.execute(
                select(models.Order).where(models.Order.state.in_(("submitted", "partial")))
            )
        ).scalars()
    }
    exchange_orders = {
        item.client_order_id: item
        for item in await source.list_open_orders()
        if item.client_order_id
    }

    for client_order_id, order in local_orders.items():
        if client_order_id in exchange_orders:
            continue
        detected += 1
        await _upsert(
            session,
            kind="order_missing_exchange",
            inst_id=order.inst_id,
            position_side=order.position_side,
            reference=client_order_id,
            instrument_id=order.instrument_id,
            strategy_id=order.strategy_id,
            local_value=order.filled_quantity,
            exchange_value=None,
            detail={"state": order.state},
            now=now,
        )
    for client_order_id, exchange_order in exchange_orders.items():
        if client_order_id in local_orders:
            continue
        detected += 1
        await _upsert(
            session,
            kind="order_missing_local",
            inst_id=exchange_order.inst_id,
            position_side=exchange_order.position_side,
            reference=client_order_id,
            exchange_value=exchange_order.filled_quantity,
            detail={"state": exchange_order.state},
            now=now,
        )

    await session.commit()
    return {
        "checked_positions": len(local_positions),
        "checked_orders": len(local_orders),
        "diffs": detected,
        "open_diffs": await open_diff_count(session),
    }


async def list_diffs(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 50,
    cursor: int | None = None,
) -> dict[str, Any]:
    statement = (
        select(models.ReconcileDiff).order_by(models.ReconcileDiff.id.desc()).limit(limit + 1)
    )
    if status is not None:
        statement = statement.where(models.ReconcileDiff.status == status)
    if cursor is not None:
        statement = statement.where(models.ReconcileDiff.id < cursor)
    rows = list((await session.execute(statement)).scalars())
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return {
        "items": [serialize_diff(row) for row in rows[:limit]],
        "next_cursor": next_cursor,
    }


async def resolve_diff(
    session: AsyncSession, diff_id: int, *, resolved_by: str, note: str | None
) -> dict[str, Any]:
    diff = await session.get(models.ReconcileDiff, diff_id)
    if diff is None:
        raise ExecutionError("not_found", f"对账差异 {diff_id} 不存在", status_code=404)
    if diff.status != OPEN:
        return serialize_diff(diff)
    diff.status = "resolved"
    diff.resolved_at = datetime.now(tz=UTC)
    diff.resolved_by = resolved_by
    diff.note = note
    diff.resolve_attempts = (diff.resolve_attempts or 0) + 1
    await session.commit()
    return serialize_diff(diff)


__all__ = [
    "list_diffs",
    "open_diff_count",
    "resolve_diff",
    "run",
    "serialize_diff",
]

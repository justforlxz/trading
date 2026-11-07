"""自动止损/平仓：不经过策略审批，直接产生 reduce-only 平仓单并写 risk_event。

触发条件：单腿浮亏占持仓均价的比例达到 `EXECUTION_STOP_LOSS_RATIO`（默认 5%）。
同一持仓已有未完成的止损单时不重复下单（幂等闸门）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.execution import models, reconcile, service
from app.execution.core import positions as position_core
from app.ports.private import PrivateTradingSource
from app.risk import service as risk_service

ZERO = Decimal("0")
OPEN_STATES = ("pending", "submitted", "partial")


def _text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


async def _has_open_stop(session: AsyncSession, valuation: position_core.PositionValuation) -> bool:
    if valuation.strategy_id is None:
        return True
    existing = (
        await session.execute(
            select(models.Order.id).where(
                models.Order.strategy_id == valuation.strategy_id,
                models.Order.instrument_id == valuation.instrument_id,
                models.Order.position_side == valuation.position_side,
                models.Order.intent == "stop",
                models.Order.state.in_(OPEN_STATES),
            )
        )
    ).first()
    return existing is not None


async def evaluate(
    session: AsyncSession,
    *,
    threshold_ratio: Decimal | None = None,
    source: PrivateTradingSource | None = None,
    now: datetime | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """扫描全部策略持仓，触发止损并返回逐条结论。"""

    current = get_settings()
    threshold = threshold_ratio or Decimal(str(current.execution_stop_loss_ratio))
    moment = now or datetime.now(tz=UTC)
    mode = service.resolve_mode()

    valuations = await service.position_valuations(session)
    triggered: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for item in valuations:
        ratio = position_core.unrealized_ratio(item)
        if ratio is None or item.strategy_id is None:
            continue
        if ratio > -threshold:
            continue
        if await _has_open_stop(session, item):
            skipped.append(
                {
                    "strategy_id": item.strategy_id,
                    "inst_id": item.inst_id,
                    "position_side": item.position_side,
                    "reason": "stop_order_open",
                }
            )
            continue

        close_side = "sell" if item.position_side == "long" else "buy"
        try:
            body, created = await service.submit_order(
                session,
                strategy_id=item.strategy_id,
                inst_id=item.inst_id,
                side=close_side,
                position_side=item.position_side,
                quantity=item.quantity,
                order_type="market",
                reduce_only=True,
                intent="stop",
                mode=mode,
                source=source,
            )
        except Exception as exc:  # 单腿失败不能拖垮整轮止损扫描
            skipped.append(
                {
                    "strategy_id": item.strategy_id,
                    "inst_id": item.inst_id,
                    "position_side": item.position_side,
                    "reason": f"submit_failed: {exc}",
                }
            )
            continue

        event_id = None
        if persist:
            event, _ = await risk_service.record_event(
                session,
                kind="stop_trigger",
                severity="tier3",
                action="close",
                strategy_id=item.strategy_id,
                instrument_id=item.instrument_id,
                policy_version=0,
                observed_value=ratio,
                threshold=-threshold,
                payload={
                    "order_id": body["id"],
                    "client_order_id": body["client_order_id"],
                    "inst_id": item.inst_id,
                    "position_side": item.position_side,
                    "quantity": _text(item.quantity),
                    "mark_price": _text(item.mark_price),
                    "triggered_at": moment.isoformat(),
                },
                evaluation_key=body["client_order_id"],
                at=moment,
            )
            event_id = event.id
            body["risk_event_id"] = event_id
            order_row = await session.get(models.Order, body["id"])
            if order_row is not None:
                order_row.risk_event_id = event_id
                await session.commit()

        triggered.append(
            {
                "strategy_id": item.strategy_id,
                "inst_id": item.inst_id,
                "position_side": item.position_side,
                "unrealized_ratio": _text(ratio),
                "order": body,
                "risk_event_id": event_id,
                "created": created,
            }
        )

    return {
        "mode": mode,
        "threshold_ratio": _text(-threshold),
        "evaluated": len(valuations),
        "triggered": triggered,
        "skipped": skipped,
        "open_diffs": await reconcile.open_diff_count(session),
    }


__all__ = ["evaluate"]

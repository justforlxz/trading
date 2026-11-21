"""K 线收盘事件 → 技术类提醒。

只有确认收盘的 K 线才是事实：上游 `confirm=0` 的推送在推送层就被丢弃，本层只接
`candle.closed`。判定完全复用 `app.alerts.technical_candidates`（MA20 穿越、RSI 进入
观察区、趋势状态变化），阈值与提醒扫描是同一份代码，事件层不重新定义。

历史取库里同周期的已有 K 线（`app.market.load_candles`），再把本次推送的那根并进去；
本层不写 K 线，落库仍走已有的按需同步。库里该周期历史不足时规则自然不成立——指标需要
足够的前置 K 线，不补造数据。

**规则名带周期前缀**（`candle1h.rsi_zone`）。提醒扫描只对自己 `SCAN_MANAGED_RULES`
里的规则按**日线**判过期；K 线事件用的是 1H 序列，如果沿用 `rsi_zone` 这类同名规则，
一次手动扫描就会按日线把它们判成「条件已恢复」。加前缀后这些提醒归事件源自己所有，
扫描不碰（与 `price_deviation` 同一约定）。

这些规则都是跃迁型：越过阈值的那根 K 线报一次，之后再次越过才再报，提醒一直停在待处理，
由用户确认或忽略；条件恢复不代表事件没有发生过，所以本层不做过期。

产出的事件不带 `state`：唯一性由 `dedup_key` 的唯一约束保证（同一根 K 线上的同一次跃迁
只落一条），如果带上按「标的 + 规则」记录的状态，同一规则的下一次跃迁会被 `dedupe`
当作「状态没变」吞掉。
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from app.alerts import AlertCandidate, record_candidate, technical_candidates
from app.core import Bar, Timeframe, ValidationError
from app.events.event import DomainEvent
from app.market import load_candles

if TYPE_CHECKING:
    from app.events.pipeline import CallNext, Middleware, PipelineDeps

__all__ = ["BAR_LOOKBACK_DAYS", "CANDLE_KIND", "RULE_PREFIX", "middleware"]

CANDLE_KIND = "candle.closed"
#: 推送来的 K 线来源：本层并进历史的那根来自上游推送，不是库里的历史。
SOURCE = "okx_ws"
#: 各周期的回看窗口（天）：1h 取 168 根、4h 取 180 根、1d 取 180 根，覆盖 MA60 与 RSI14。
BAR_LOOKBACK_DAYS: dict[str, int] = {"1h": 7, "4h": 30, "1d": 180}
#: 规则名前缀：与提醒扫描的日线规则区分开（`candle1h.rsi_zone`）。
RULE_PREFIX = "candle"


def middleware(_deps: PipelineDeps) -> Middleware:
    async def technical(event: DomainEvent, call_next: CallNext) -> None:
        if event.kind != CANDLE_KIND or event.inst_id is None:
            await call_next(event)
            return
        bar = _closed_bar(event.inst_id, dict(event.payload))
        if bar is None:
            return
        candidates = await asyncio.to_thread(_candidates, bar, event.occurred_at)
        if not candidates:
            await call_next(event)
            return
        for candidate in candidates:
            alert = await asyncio.to_thread(record_candidate, candidate)
            if alert is None:  # 这根 K 线的这次跃迁已经落过：不重复投递
                continue
            await call_next(
                DomainEvent(
                    kind="alert",
                    inst_id=candidate.instrument_id,
                    payload={"rule_id": candidate.rule_id, "alert": alert},
                    occurred_at=candidate.triggered_at,
                )
            )

    return technical


def _closed_bar(inst_id: str, payload: dict[str, Any]) -> Bar | None:
    """把事件载荷还原成一根已收盘的 K 线；未收盘或字段不全时返回 `None`。"""

    if payload.get("confirm") is not True:
        return None
    try:
        return Bar(
            inst_id=inst_id,
            timeframe=Timeframe.parse(str(payload.get("bar") or "")),
            open_time=datetime.fromisoformat(str(payload.get("open_time") or "")),
            open=Decimal(str(payload["open"])),
            high=Decimal(str(payload["high"])),
            low=Decimal(str(payload["low"])),
            close=Decimal(str(payload["close"])),
            volume=Decimal(str(payload["volume"])),
            confirm=True,
            source=SOURCE,
        )
    except (InvalidOperation, KeyError, TypeError, ValueError, ValidationError):
        return None


def _candidates(bar: Bar, moment: datetime) -> list[AlertCandidate]:
    """该周期历史 + 本次推送的这根 → 技术类候选；规则名与去重键带上周期。"""

    days = BAR_LOOKBACK_DAYS.get(bar.timeframe.value)
    if days is None:
        return []
    history = load_candles(
        bar.inst_id, bar.timeframe.value, start=bar.open_time - timedelta(days=days)
    )
    bars = [item for item in history if item.open_time < bar.open_time]
    return [
        _scoped(candidate, bar.timeframe.value)
        for candidate in technical_candidates(bar.inst_id, [*bars, bar], moment=moment)
    ]


def _scoped(candidate: AlertCandidate, bar: str) -> AlertCandidate:
    """规则名加周期前缀，去重键补周期后缀：两条时间轴上的同一次跃迁互不覆盖。"""

    return replace(
        candidate,
        rule_id=f"{RULE_PREFIX}{bar}.{candidate.rule_id}",
        dedup_key=f"{candidate.dedup_key}|{bar}",
    )

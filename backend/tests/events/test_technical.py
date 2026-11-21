"""K 线收盘事件 → 技术类提醒：只认收盘、口径复用提醒扫描、不参与日线过期。

用例直接调用管线（不经过 `StreamHub`）：库里放同周期的历史 K 线，再注入一根推送的
收盘 K 线，断言「收盘推送 → 提醒落库 → 通道收到」这条完整链路。推送的那根不写库，
与实现一致（K 线落库仍走已有的按需同步）。
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.alerts import AlertEventRow, scan_alerts
from app.alerts.rules import RSI_LOWER, SCAN_MANAGED_RULES
from app.core import Bar, Timeframe
from app.db import session_scope
from app.events import DomainEvent, NotificationDeliveryRow, build_pipeline, build_sinks
from app.instrument import sync_instruments
from app.market import upsert_candles
from tests.factories.instruments import make_swap_ref

SYMBOL = make_swap_ref().inst_id
START = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
# 20 根稳步上行后掉头：第 23 根的 RSI14 从 30.39 降到 23.91，正好越过 RSI_LOWER。
_RISING: tuple[int, ...] = tuple(100 + index for index in range(20))
CROSSING: tuple[Decimal, ...] = tuple(Decimal(value) for value in (*_RISING, 100, 90, 80))
# 同一条序列再回升两根、回落两根：第 27 根又一次下穿 RSI_LOWER。
SECOND_CROSSING: tuple[Decimal, ...] = (
    *CROSSING,
    Decimal(83),
    Decimal(86),
    Decimal(83),
    Decimal(80),
)


class RecordingBroadcast:
    """记录浏览器通道的广播调用，不真的连 WS。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], Any]] = []

    def __call__(self, event_type: str, data: dict[str, Any], as_of: Any, predicate: Any) -> None:
        self.calls.append((event_type, data, as_of))


def _bars(closes: tuple[Decimal, ...]) -> list[Bar]:
    return [
        Bar(
            inst_id=SYMBOL,
            timeframe=Timeframe.parse("1h"),
            open_time=START + timedelta(hours=index),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=Decimal("1"),
            confirm=True,
            source="okx_rest",
        )
        for index, close in enumerate(closes)
    ]


def _seed(closes: tuple[Decimal, ...]) -> None:
    """把历史 K 线写进库：库里只有已收盘的 K 线（`upsert_candles` 自己丢弃未收盘的）。"""

    sync_instruments([make_swap_ref()])
    upsert_candles(_bars(closes))


def _closed_event(bar: Bar, *, confirm: bool = True) -> DomainEvent:
    """与 `StreamHub._handle_candle` 相同的载荷形状：这一根 K 线的全部字段。"""

    return DomainEvent(
        kind="candle.closed",
        inst_id=bar.inst_id,
        payload={
            "bar": bar.timeframe.value,
            "open_time": bar.open_time.isoformat().replace("+00:00", "Z"),
            "open": str(bar.open),
            "high": str(bar.high),
            "low": str(bar.low),
            "close": str(bar.close),
            "volume": str(bar.volume),
            "confirm": confirm,
        },
        occurred_at=bar.open_time,
    )


def _pipeline(broadcast: RecordingBroadcast):
    return build_pipeline(sinks=build_sinks(channels=["browser"], broadcast=broadcast))


def _alerts() -> list[AlertEventRow]:
    with session_scope() as session:
        return list(session.scalars(select(AlertEventRow).order_by(AlertEventRow.triggered_at)))


def _deliveries() -> list[NotificationDeliveryRow]:
    with session_scope() as session:
        return list(session.scalars(select(NotificationDeliveryRow)))


def test_a_closed_candle_across_the_rsi_threshold_lands_one_alert_and_one_delivery() -> None:
    """AC3：越过阈值的收盘 K 线 → 技术类提醒落库并进入投递链路。"""

    pushed = _bars(CROSSING)[-1]
    _seed(CROSSING[:-1])
    broadcast = RecordingBroadcast()

    asyncio.run(_pipeline(broadcast).run(_closed_event(pushed)))

    alerts = _alerts()
    assert len(alerts) == 1
    alert = alerts[0]
    assert (alert.type, alert.rule_id, alert.status) == (
        "indicator",
        "candle1h.rsi_zone",
        "pending",
    )
    assert alert.instrument_id == SYMBOL
    assert alert.triggered_at == pushed.open_time
    payload = json.loads(alert.payload_json)
    # 阈值来自提醒扫描的同一份实现，不在事件层另定一个数。
    assert payload["threshold"] == str(RSI_LOWER)

    assert [call[0] for call in broadcast.calls] == ["alert.created"]
    assert broadcast.calls[0][1]["id"] == alert.id
    assert [(row.channel, row.alert_id, row.status) for row in _deliveries()] == [
        ("browser", alert.id, "delivered")
    ]


def test_the_candle_rules_are_not_managed_by_the_daily_scan() -> None:
    """规则名带周期前缀：日线扫描不按自己那条时间轴判这些提醒过期。"""

    pushed = _bars(CROSSING)[-1]
    _seed(CROSSING[:-1])
    broadcast = RecordingBroadcast()
    asyncio.run(_pipeline(broadcast).run(_closed_event(pushed)))
    assert _alerts()[0].rule_id not in SCAN_MANAGED_RULES

    scan_alerts()

    alerts = _alerts()
    assert [row.rule_id for row in alerts] == ["candle1h.rsi_zone"]
    assert [row.status for row in alerts] == ["pending"]


def test_an_unconfirmed_candle_produces_no_alert_and_no_delivery() -> None:
    """AC2：`confirm=0` 的 K 线还会变动，不能当成事实。"""

    pushed = _bars(CROSSING)[-1]
    _seed(CROSSING[:-1])
    broadcast = RecordingBroadcast()

    asyncio.run(_pipeline(broadcast).run(_closed_event(pushed, confirm=False)))

    assert _alerts() == []
    assert _deliveries() == []
    assert broadcast.calls == []


def test_a_closed_candle_inside_the_threshold_produces_nothing() -> None:
    """收盘 K 线没有跃迁时不产生提醒：规则只在越过阈值的那一根触发。"""

    # 从超卖区回升的那一根：RSI14 从 23.9 回到 30 以上，没有穿过任何阈值。
    pushed = _bars(SECOND_CROSSING)[23]
    _seed(SECOND_CROSSING[:23])
    broadcast = RecordingBroadcast()

    asyncio.run(_pipeline(broadcast).run(_closed_event(pushed)))

    assert _alerts() == []
    assert broadcast.calls == []


def test_replaying_the_same_closed_bar_delivers_once() -> None:
    """重连后的重放：同一根 K 线上的同一次跃迁只落一条提醒、只投递一次。"""

    pushed = _bars(CROSSING)[-1]
    _seed(CROSSING[:-1])
    broadcast = RecordingBroadcast()
    pipeline = _pipeline(broadcast)

    async def scenario() -> None:
        await pipeline.run(_closed_event(pushed))
        await pipeline.run(_closed_event(pushed))

    asyncio.run(scenario())

    assert len(_alerts()) == 1
    assert len(broadcast.calls) == 1
    assert len(_deliveries()) == 1


def test_two_crossings_on_the_same_rule_both_get_delivered() -> None:
    """同一规则的第二次跃迁不会被去重状态机吞掉：每根 K 线各算一次。"""

    bars = _bars(SECOND_CROSSING)
    _seed(SECOND_CROSSING)
    broadcast = RecordingBroadcast()
    pipeline = _pipeline(broadcast)

    first, second = bars[22], bars[26]

    async def scenario() -> None:
        await pipeline.run(_closed_event(first))
        await pipeline.run(_closed_event(second))

    asyncio.run(scenario())

    alerts = _alerts()
    assert [row.triggered_at for row in alerts] == [first.open_time, second.open_time]
    assert [row.rule_id for row in alerts] == ["candle1h.rsi_zone", "candle1h.rsi_zone"]
    assert len(broadcast.calls) == 2
    assert len(_deliveries()) == 2

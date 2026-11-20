"""规则状态机：一条推送越界一次只产出一条提醒，回落后再越界再产出一条。

用例直接调用管线（不经过 hub），因此断言的是「推送进来 → 提醒落库 → 通道收到」这条
完整链路，与定时器无关：管线只被 `run` 一次，没有周期动作。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.alerts import AlertEventRow
from app.db import session_scope
from app.events import DomainEvent, NotificationDeliveryRow, build_pipeline, build_sinks
from app.events.middlewares import rule_engine
from app.events.middlewares.rule_engine import DEVIATION_THRESHOLD_PCT, RULE_ID
from app.events.sinks.base import DeliveryResult
from app.events.sinks.registry import SinkRegistry
from app.instrument import sync_instruments
from tests.factories.instruments import make_swap_ref

SYMBOL = make_swap_ref().inst_id
START = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


class RecordingBroadcast:
    """记录浏览器通道的广播调用，不真的连 WS。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], Any]] = []

    def __call__(self, event_type: str, data: dict[str, Any], as_of: Any, predicate: Any) -> None:
        assert predicate(_Browser(alerts=True)) is True
        assert predicate(_Browser(alerts=False)) is False
        self.calls.append((event_type, data, as_of))


class RecordingSink:
    """接收除告警以外事件的假通道，用来核对中间件没有吞掉事实。"""

    name = "recording"

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def accepts(self, event: DomainEvent) -> bool:
        return event.kind in {"account", "position"}

    async def deliver(self, event: DomainEvent) -> DeliveryResult:
        self.events.append(event)
        return DeliveryResult(channel=self.name, status="delivered")


class MemoryRecorder:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str | None]] = []

    async def __call__(self, result: DeliveryResult, alert_id: str | None) -> None:
        self.rows.append((result.channel, alert_id))


class _Browser:
    def __init__(self, *, alerts: bool) -> None:
        self.alerts = alerts


def _pipeline(broadcast: RecordingBroadcast):
    return build_pipeline(sinks=build_sinks(channels=["browser"], broadcast=broadcast))


def _quote(*, last: str, index: str, offset: int) -> DomainEvent:
    return DomainEvent(
        kind="quote",
        inst_id=SYMBOL,
        payload={"inst_id": SYMBOL, "last": last, "index": index, "source": "okx_ws"},
        occurred_at=START + timedelta(seconds=offset),
    )


def _alerts() -> list[AlertEventRow]:
    with session_scope() as session:
        return list(session.scalars(select(AlertEventRow).order_by(AlertEventRow.triggered_at)))


def _expired_activity() -> list[Any]:
    from app.activity import list_activity

    records, _ = list_activity(event_type="alert.expired", limit=50)
    return list(records)


def _deliveries() -> list[NotificationDeliveryRow]:
    with session_scope() as session:
        return list(session.scalars(select(NotificationDeliveryRow)))


def test_threshold_comes_from_the_market_domain() -> None:
    """阈值与跨源偏离共用同一个默认值，不在事件层另定一个数。"""

    from app.market import DEFAULT_THRESHOLD_PCT

    assert DEVIATION_THRESHOLD_PCT == DEFAULT_THRESHOLD_PCT


def test_a_pushed_quote_over_the_threshold_lands_one_alert_and_one_delivery() -> None:
    """AC4：一条越界推送 → 提醒落库 + 浏览器通道收到一次广播 + 台账一行。"""

    sync_instruments([make_swap_ref()])
    broadcast = RecordingBroadcast()
    pipeline = _pipeline(broadcast)

    asyncio.run(pipeline.run(_quote(last="110", index="100", offset=0)))

    alerts = _alerts()
    assert len(alerts) == 1
    assert alerts[0].rule_id == RULE_ID
    assert alerts[0].type == "price"
    assert alerts[0].instrument_id == SYMBOL
    assert alerts[0].payload_json is not None and "10" in alerts[0].payload_json

    assert [call[0] for call in broadcast.calls] == ["alert.created"]
    assert broadcast.calls[0][1]["id"] == alerts[0].id
    assert broadcast.calls[0][2] == START

    deliveries = _deliveries()
    assert [(row.channel, row.alert_id, row.status) for row in deliveries] == [
        ("browser", alerts[0].id, "delivered")
    ]


def test_five_consecutive_crossings_deliver_once_and_a_fall_back_rearms() -> None:
    """AC5：连续 5 次越过阈值只投递 1 次；回落后再越界再投 1 次。"""

    sync_instruments([make_swap_ref()])
    broadcast = RecordingBroadcast()
    pipeline = _pipeline(broadcast)

    async def scenario() -> None:
        for offset in range(5):
            await pipeline.run(_quote(last="110", index="100", offset=offset))
        # 回落到阈值内：只清除状态，不产生提醒
        await pipeline.run(_quote(last="100.5", index="100", offset=10))
        # 再次越界：重新布防后的一次
        await pipeline.run(_quote(last="111", index="100", offset=11))
        # 仍在阈值外：不重复
        await pipeline.run(_quote(last="112", index="100", offset=12))

    asyncio.run(scenario())

    assert len(_alerts()) == 2
    assert len(broadcast.calls) == 2
    assert [row.status for row in _deliveries()] == ["delivered", "delivered"]


def test_falling_back_closes_the_pending_alert() -> None:
    """AC9 另一半：回落时提醒落成 expired，待处理列表不会只进不出。"""

    sync_instruments([make_swap_ref()])
    broadcast = RecordingBroadcast()
    pipeline = _pipeline(broadcast)

    async def scenario() -> None:
        await pipeline.run(_quote(last="110", index="100", offset=0))
        assert [row.status for row in _alerts()] == ["pending"]
        await pipeline.run(_quote(last="100.4", index="100", offset=1))
        # 仍在阈值内再推一次：已经关闭的行不会被重复写活动
        await pipeline.run(_quote(last="100.2", index="100", offset=2))

    asyncio.run(scenario())

    alerts = _alerts()
    assert [row.status for row in alerts] == ["expired"]
    assert alerts[0].expires_at is not None

    activities = _expired_activity()
    assert [item.object_id for item in activities] == [alerts[0].id]
    assert activities[0].payload["previous_status"] == "pending"

    # 关闭之后待处理列表里没有它，再越界会产生新的一条
    with session_scope() as session:
        pending = list(
            session.scalars(
                select(AlertEventRow).where(
                    AlertEventRow.rule_id == RULE_ID, AlertEventRow.status == "pending"
                )
            )
        )
    assert pending == []


def test_a_quote_inside_the_threshold_never_produces_an_alert() -> None:
    sync_instruments([make_swap_ref()])
    broadcast = RecordingBroadcast()

    asyncio.run(
        _pipeline(broadcast).run(_quote(last="102.99", index="100", offset=0)),
    )

    assert _alerts() == []
    assert broadcast.calls == []


def test_a_quote_exactly_on_the_threshold_counts_as_a_crossing() -> None:
    """边界与 `app.market.divergence` 一致：达到阈值即越界。"""

    sync_instruments([make_swap_ref()])
    broadcast = RecordingBroadcast()

    asyncio.run(_pipeline(broadcast).run(_quote(last="103", index="100", offset=0)))

    assert len(_alerts()) == 1
    assert len(broadcast.calls) == 1


def test_a_failed_alert_write_does_not_swallow_the_crossing(monkeypatch: Any) -> None:
    """落库失败时状态退回未触发：下一笔推送会重新判定并在库可用时补上。"""

    sync_instruments([make_swap_ref()])
    broadcast = RecordingBroadcast()
    fail = {"left": 1}
    original = rule_engine._record_alert

    def flaky(decision: Any) -> Any:
        if fail["left"] > 0:
            fail["left"] -= 1
            return None
        return original(decision)

    monkeypatch.setattr(rule_engine, "_record_alert", flaky)
    pipeline = _pipeline(broadcast)

    async def scenario() -> None:
        await pipeline.run(_quote(last="110", index="100", offset=0))
        await pipeline.run(_quote(last="110", index="100", offset=1))

    asyncio.run(scenario())

    assert len(_alerts()) == 1
    assert len(broadcast.calls) == 1


def test_account_and_position_events_reach_the_sinks() -> None:
    """非行情事件没有研判规则，但不能被规则中间件吞掉。"""

    sink = RecordingSink()
    pipeline = build_pipeline(sinks=SinkRegistry([sink], recorder=MemoryRecorder()))

    async def scenario() -> None:
        await pipeline.run(
            DomainEvent(kind="account", inst_id=None, payload={"equity": "100"}, occurred_at=START)
        )
        await pipeline.run(
            DomainEvent(
                kind="position",
                inst_id=SYMBOL,
                payload={"pos_id": "p1"},
                occurred_at=START,
            )
        )

    asyncio.run(scenario())

    assert [event.kind for event in sink.events] == ["account", "position"]

"""通道隔离：关掉 browser 后不再广播，其它通道照常投递。

用例不连 WS，也不发真实通知：`broadcast` 是一个记录调用次数的假函数，其它通道用
记录型假实现。断言的是「哪个通道被构造、收到了什么」。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from app.events import DeliveryDigest, DomainEvent, build_pipeline, build_sinks
from app.events.sinks.base import DeliveryResult
from app.events.sinks.registry import SinkRegistry

MOMENT = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


class RecordingBroadcast:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, event_type: str, data: dict[str, Any], _as_of: Any, _predicate: Any) -> None:
        self.calls.append((event_type, data))


class FakeSink:
    """另一个通道：只证明自己也收到了同一条告警。"""

    name = "fake"

    def __init__(self) -> None:
        self.digests: list[DeliveryDigest] = []

    async def deliver(self, digest: DeliveryDigest) -> DeliveryResult:
        self.digests.append(digest)
        return DeliveryResult(channel=self.name, status="delivered")


class BrokenSink(FakeSink):
    name = "broken"

    async def deliver(self, digest: DeliveryDigest) -> DeliveryResult:
        raise RuntimeError("通道不可用")


class MemoryRecorder:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str | None]] = []

    async def __call__(self, result: DeliveryResult, alert_id: str | None) -> None:
        self.rows.append((result.channel, result.status, result.error))


def _alert(*, minutes: int = 0) -> DomainEvent:
    return DomainEvent(
        kind="alert",
        inst_id="XAAPL-USDT",
        payload={
            "rule_id": "test_rule",
            "state": "triggered",
            "alert": {
                "id": "al_1",
                "type": "price",
                "severity": "warning",
                "title": "价格偏离参考价",
                "detail": "XAAPL-USDT 最新成交价 101.5 高于 指数价 100",
                "instrument_id": "XAAPL-USDT",
            },
        },
        occurred_at=MOMENT + timedelta(minutes=minutes),
    )


def test_disabled_browser_channel_does_not_broadcast() -> None:
    """AC7：配置里没有 browser 时，浏览器通道根本不会被构造。"""

    broadcast = RecordingBroadcast()
    registry = build_sinks(channels=[], broadcast=broadcast)

    asyncio.run(registry.deliver(_alert()))

    assert registry.channels == ()
    assert broadcast.calls == []


def test_other_channels_keep_delivering_when_browser_is_off() -> None:
    broadcast = RecordingBroadcast()
    fake = FakeSink()
    recorder = MemoryRecorder()
    sinks = SinkRegistry([fake], recorder=recorder)

    async def scenario() -> None:
        pipeline = build_pipeline(sinks=sinks)
        await pipeline.run(_alert())

    asyncio.run(scenario())

    assert [digest.items[0].alert["id"] for digest in fake.digests] == ["al_1"]
    assert recorder.rows == [("fake", "delivered", None)]
    assert broadcast.calls == []


def test_enabling_browser_broadcasts_only_the_alerts_subscribers() -> None:
    broadcast = RecordingBroadcast()
    registry = build_sinks(channels=["browser"], broadcast=broadcast)

    async def scenario() -> None:
        await registry.deliver(_alert())

    asyncio.run(scenario())

    assert [call[0] for call in broadcast.calls] == ["alert.created"]
    assert broadcast.calls[0][1]["id"] == "al_1"
    assert broadcast.calls[0][1]["message"].startswith("⚠️ 价格区间 · 警告")


def test_turning_a_channel_off_at_runtime_stops_broadcasting() -> None:
    """设置页保存后立即生效：同一个注册表按新清单过滤，不用重启进程。"""

    broadcast = RecordingBroadcast()
    registry = build_sinks(channels=["browser"], broadcast=broadcast)

    async def scenario() -> None:
        await registry.deliver(_alert())
        registry.set_channels([])
        await registry.deliver(_alert(minutes=11))
        registry.set_channels(["browser"])
        await registry.deliver(_alert(minutes=22))

    asyncio.run(scenario())

    assert [call[1]["id"] for call in broadcast.calls] == ["al_1", "al_1"]
    assert registry.channels == ("browser",)


def test_unknown_channel_names_are_ignored_not_faked() -> None:
    registry = build_sinks(channels=["imessage", "browser"], broadcast=RecordingBroadcast())

    assert registry.channels == ("browser",)


def test_non_alert_events_never_reach_a_channel() -> None:
    """行情、账户这类事实没有可投递的正文：不投递，也不写台账。"""

    sink = FakeSink()
    recorder = MemoryRecorder()
    registry = SinkRegistry([sink], recorder=recorder)

    asyncio.run(
        registry.deliver(DomainEvent(kind="quote", inst_id="XAAPL-USDT", occurred_at=MOMENT))
    )

    assert sink.digests == []
    assert recorder.rows == []


def test_a_failing_channel_is_recorded_as_failed() -> None:
    recorder = MemoryRecorder()
    registry = SinkRegistry([BrokenSink()], recorder=recorder)

    asyncio.run(registry.deliver(_alert()))

    assert recorder.rows == [("broken", "failed", "通道不可用")]

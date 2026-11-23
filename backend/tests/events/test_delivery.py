"""投递路径：按通道的类型订阅、最低严重度、合并窗口与一轮一摘要。

用例把通道换成记录型替身，台账换成内存记录：断言的是「该不该投、投了几次、正文长
什么样」，不连外部服务，也不写库。合并窗口按告警自身的时刻计算，所以这里用固定的
事件时刻，不依赖真实时钟。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from app.events import (
    DEFAULT_SUBSCRIPTIONS,
    DeliveryDigest,
    DeliveryResult,
    DomainEvent,
    resolve_subscriptions,
)
from app.events.sinks.registry import SinkRegistry
from app.events.sinks.render import render_message

BASE = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


class RecordingSink:
    name = "telegram"

    def __init__(self) -> None:
        self.digests: list[DeliveryDigest] = []

    async def deliver(self, digest: DeliveryDigest) -> DeliveryResult:
        self.digests.append(digest)
        return DeliveryResult(channel=self.name, status="delivered")


class MemoryRecorder:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str | None]] = []

    async def __call__(self, result: DeliveryResult, alert_id: str | None) -> None:
        self.rows.append((result.channel, alert_id))


def _alert(
    *,
    alert_id: str = "al_1",
    type_: str = "indicator",
    severity: str = "info",
    instrument: str = "XAAPL-USDT",
    title: str = "收盘价跌破 MA20",
    minutes: int = 0,
) -> DomainEvent:
    return DomainEvent(
        kind="alert",
        inst_id=instrument,
        payload={
            "rule_id": "candle1h.ma20_cross",
            "alert": {
                "id": alert_id,
                "type": type_,
                "severity": severity,
                "title": title,
                "detail": f"{instrument} 收盘价 101 跌破 MA20（102）",
                "instrument_id": instrument,
            },
        },
        occurred_at=BASE + timedelta(minutes=minutes),
    )


def _registry(
    sink: RecordingSink,
    *,
    subscriptions: dict[str, Any] | None = None,
    recorder: MemoryRecorder | None = None,
) -> SinkRegistry:
    return SinkRegistry(
        [sink],
        recorder=recorder or MemoryRecorder(),
        subscriptions=(lambda: subscriptions if subscriptions is not None else {}),
    )


# --------------------------------------------------------- 订阅与严重度


def test_default_subscriptions_mute_telegram_indicator_alerts() -> None:
    """AC2：Telegram 默认只收 risk + strategy；提示级技术形态不投、不写台账。"""

    sink = RecordingSink()
    recorder = MemoryRecorder()
    registry = _registry(sink, recorder=recorder)

    asyncio.run(registry.deliver_round([_alert(type_="indicator", severity="info")]))

    assert sink.digests == []
    assert recorder.rows == []


def test_a_subscribed_type_is_delivered() -> None:
    """AC2 另一半：risk 在默认订阅里，照样投递并记一行台账。"""

    sink = RecordingSink()
    recorder = MemoryRecorder()
    registry = _registry(sink, recorder=recorder)

    asyncio.run(
        registry.deliver_round([_alert(type_="risk", severity="warning", title="杠杆过高")])
    )

    assert len(sink.digests) == 1
    assert recorder.rows == [("telegram", "al_1")]


def test_min_severity_blocks_lower_severities() -> None:
    """AC3：最低严重度是 warning 时，info 不进 Telegram。"""

    sink = RecordingSink()
    registry = _registry(
        sink,
        subscriptions={"telegram": {"types": ["risk"], "min_severity": "warning"}},
    )

    async def scenario() -> None:
        await registry.deliver_round([_alert(alert_id="al_info", type_="risk", severity="info")])
        await registry.deliver_round(
            [_alert(alert_id="al_warn", type_="risk", severity="warning", minutes=11)]
        )

    asyncio.run(scenario())

    assert [digest.items[0].alert["id"] for digest in sink.digests] == ["al_warn"]


def test_configured_types_replace_only_their_own_channel() -> None:
    """只配 telegram 时，其它通道仍按默认值：浏览器全收、webhook 空。"""

    resolved = resolve_subscriptions({"telegram": {"types": ["data"]}})

    assert resolved["telegram"].types == ("data",)
    assert resolved["telegram"].min_severity == "warning"
    assert resolved["browser"].types == tuple(DEFAULT_SUBSCRIPTIONS["browser"]["types"])
    assert resolved["webhook"].types == ()


def test_unknown_types_and_severities_fall_back_to_defaults() -> None:
    """设置文档里的坏值不让投递停摆：整项回落到默认值。"""

    resolved = resolve_subscriptions(
        {"telegram": {"types": ["no_such_type"], "min_severity": "apocalyptic"}}
    )

    assert resolved["telegram"].types == ()
    assert resolved["telegram"].min_severity == "warning"


# ------------------------------------------------------------- 降频三层


def test_three_alerts_inside_one_round_become_one_delivery_marked_with_x3() -> None:
    """AC4：同一轮里同 (标的, 类型) 的 3 条 → 1 次投递，正文带 ×3。"""

    sink = RecordingSink()
    registry = _registry(
        sink,
        subscriptions={"telegram": {"types": ["indicator"], "min_severity": "info"}},
    )

    asyncio.run(
        registry.deliver_round(
            [
                _alert(alert_id="al_1"),
                _alert(alert_id="al_2", title="RSI 进入超卖观察区"),
                _alert(alert_id="al_3", title="趋势状态变化"),
            ]
        )
    )

    assert len(sink.digests) == 1
    digest = sink.digests[0]
    assert digest.total == 3
    assert digest.items[0].count == 3
    assert "×3" in render_message(digest)


def test_five_alerts_in_one_round_produce_one_summary() -> None:
    """AC5：一轮 5 条 → 1 次投递，首行含「本轮 5 条」与类型分布。"""

    sink = RecordingSink()
    recorder = MemoryRecorder()
    registry = _registry(
        sink,
        recorder=recorder,
        subscriptions={
            "telegram": {
                "types": ["risk", "indicator", "price", "strategy", "data"],
                "min_severity": "info",
            }
        },
    )

    alerts = [
        _alert(alert_id="al_1", type_="risk", severity="warning", title="杠杆过高"),
        _alert(alert_id="al_2", type_="risk", severity="warning", title="止损距离过近"),
        _alert(alert_id="al_3", type_="risk", severity="warning", title="单标的占比过高"),
        _alert(alert_id="al_4", type_="indicator", title="收盘价跌破 MA20"),
        _alert(alert_id="al_5", type_="indicator", title="RSI 进入超卖观察区"),
    ]

    asyncio.run(registry.deliver_round(alerts))

    assert len(sink.digests) == 1
    assert len(recorder.rows) == 1
    assert sink.digests[0].total == 5
    assert sink.digests[0].type_counts() == (("risk", 3), ("indicator", 2))


def test_the_same_key_is_muted_for_ten_minutes_and_the_count_catches_up() -> None:
    """合并窗口：同 (通道, 标的, 类型) 10 分钟内只投一次，挡下的条数并入下一次。"""

    sink = RecordingSink()
    registry = _registry(
        sink,
        subscriptions={"telegram": {"types": ["indicator"], "min_severity": "info"}},
    )

    async def scenario() -> None:
        await registry.deliver_round([_alert(alert_id="al_1")])
        await registry.deliver_round([_alert(alert_id="al_2", minutes=3)])
        await registry.deliver_round([_alert(alert_id="al_3", minutes=6)])
        # 窗口外的第四条：放行，并把被挡下的两条一起计入 ×3
        await registry.deliver_round([_alert(alert_id="al_4", minutes=12)])

    asyncio.run(scenario())

    assert [digest.total for digest in sink.digests] == [1, 3]


def test_a_different_instrument_is_not_muted_by_another_one() -> None:
    sink = RecordingSink()
    registry = _registry(
        sink,
        subscriptions={"telegram": {"types": ["indicator"], "min_severity": "info"}},
    )

    async def scenario() -> None:
        await registry.deliver_round([_alert(alert_id="al_1", instrument="XAAPL-USDT")])
        await registry.deliver_round([_alert(alert_id="al_2", instrument="BTC-USDT-SWAP")])

    asyncio.run(scenario())

    assert len(sink.digests) == 2


# ----------------------------------------------------------- 一轮的边界


def test_a_round_collects_alerts_and_delivers_once_at_the_end() -> None:
    """一轮的批次由开始/结束界定：中间收几条都不投，结束时一次投出去。"""

    sink = RecordingSink()
    recorder = MemoryRecorder()
    registry = _registry(
        sink,
        recorder=recorder,
        subscriptions={"telegram": {"types": ["indicator"], "min_severity": "info"}},
    )

    async def scenario() -> None:
        registry.begin_round()
        registry.collect(_alert(alert_id="al_1"))
        registry.collect(_alert(alert_id="al_2", instrument="BTC-USDT-SWAP"))
        registry.collect(DomainEvent(kind="quote", inst_id="XAAPL-USDT", occurred_at=BASE))
        assert sink.digests == []
        await registry.end_round()

    asyncio.run(scenario())

    assert len(sink.digests) == 1
    assert sink.digests[0].total == 2
    assert len(recorder.rows) == 1


def test_an_empty_round_writes_nothing() -> None:
    sink = RecordingSink()
    recorder = MemoryRecorder()
    registry = _registry(sink, recorder=recorder)

    async def scenario() -> None:
        registry.begin_round()
        await registry.end_round()

    asyncio.run(scenario())

    assert sink.digests == []
    assert recorder.rows == []

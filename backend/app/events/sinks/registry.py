"""通道注册表：按配置决定启用哪些通道，并记录每次投递。

四条约定：

- **注册只在这里**。新通道 = 实现 `Sink` + 在 `CHANNEL_BUILDERS` 加一行；
  `stream/hub.py`、`alerts/` 与所有中间件都不用改。
- **配置来自 `settings` 表**（`notifications.channels` 与 `notifications.subscriptions`），
  不在仓库里写死开关；不认识的通道名直接忽略，不假装支持。当前实现三种：`browser`、
  `telegram`、`webhook`。
- **开关立即生效**。设置页保存后调用 `events.apply_channels`，装好的管线把自己的
  注册表按新清单过滤，不需要重启进程；进程启动时按同一份配置装配一次。订阅也一样：
  每次投递现读，保存后下一轮评估就按新配置过滤。
- **一轮一次投递**。管线在轮次开始时让注册表开一个批次，轮次里的告警都收进这一批，
  轮次结束时统一投递：同一轮的多条合并成一条摘要，同一 `(标的, 类型)` 在合并窗口内
  只投一次。没有通道订阅这类告警时，什么也不写——台账只记真实投递。

每次投递写一行 `notification_deliveries`（通道、告警、状态、错误、时间），时间取注入
的时钟，与项目其它模块一致。写台账失败只记录日志，不影响推送本身。

外部通道（Telegram、Webhook）的地址与凭据不在这里读：装配根把「每次投递现读的配置」
作为 `SinkDeps.config` 注入，所以设置页改完地址立即生效，也不需要让事件层依赖设置域。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.core import Clock, SystemClock
from app.db import session_scope
from app.events.event import DomainEvent
from app.events.sinks.base import (
    DeliveryResult,
    NotificationDeliveryRow,
    Sink,
    alert_payload,
)
from app.events.sinks.browser import BrowserSink
from app.events.sinks.config import ChannelConfig
from app.events.sinks.digest import (
    DeliveryDigest,
    DigestItem,
    MergeWindow,
    group_digest,
)
from app.events.sinks.subscriptions import resolve_subscriptions
from app.events.sinks.telegram import TelegramSink
from app.events.sinks.webhook import WebhookSink

__all__ = [
    "CHANNEL_BUILDERS",
    "DeliveryRecorder",
    "SinkRegistry",
    "build_channel",
    "build_sinks",
    "list_deliveries",
    "record_delivery",
]

logger = logging.getLogger(__name__)


def _empty_config() -> ChannelConfig:
    """没有任何通道配置时的默认值：三项都算「未配置」。"""

    return ChannelConfig()


def _empty_subscriptions() -> Mapping[str, Any]:
    """没有任何订阅配置时返回空映射：三个通道各自按默认订阅运行。"""

    return {}


@dataclass(frozen=True, slots=True)
class SinkDeps:
    """通道构造参数：推送入口与通道配置的读取方式都由装配根注入。"""

    broadcast: Callable[..., None]
    #: 每次投递时现读配置：设置页保存后立即生效，不用重启进程。
    config: Callable[[], ChannelConfig] = _empty_config


ChannelBuilder = Callable[[SinkDeps], Sink]
#: `(投递结果, 告警标识) -> None`：投递台账的写入方式，测试可换成内存记录。
DeliveryRecorder = Callable[[DeliveryResult, str | None], Awaitable[None]]

#: 通道注册表：配置里出现哪个名字就构造哪个通道。
CHANNEL_BUILDERS: dict[str, ChannelBuilder] = {
    "browser": lambda deps: BrowserSink(deps.broadcast),
    "telegram": lambda deps: TelegramSink(deps.config),
    "webhook": lambda deps: WebhookSink(deps.config),
}


class SinkRegistry:
    """已构造的通道集合；负责按开关过滤、投递与投递台账。"""

    def __init__(
        self,
        sinks: Sequence[Sink] = (),
        *,
        enabled: Iterable[str] | None = None,
        recorder: DeliveryRecorder | None = None,
        clock: Clock | None = None,
        subscriptions: Callable[[], Mapping[str, Any]] = _empty_subscriptions,
        window: MergeWindow | None = None,
    ) -> None:
        self._sinks = tuple(sinks)
        self._clock = clock or SystemClock()
        self._enabled: set[str] | None = None if enabled is None else set(enabled)
        self._recorder = recorder or self._record_to_database
        self._subscriptions = subscriptions
        self._window = window or MergeWindow()
        self._round: list[DomainEvent] | None = None

    @property
    def channels(self) -> tuple[str, ...]:
        """当前启用（且已实现）的通道名。"""

        return tuple(sink.name for sink in self._active())

    def set_channels(self, channels: Iterable[str]) -> None:
        """按新的开关清单过滤；不在清单里的通道立即停止投递。"""

        self._enabled = set(channels)

    def begin_round(self) -> None:
        """管线开始一轮评估：开一个空批次，轮次里的告警都收进来。"""

        self._round = []

    def collect(self, event: DomainEvent) -> None:
        """把一轮里产出的告警收进批次；行情、账户这类事实不留。"""

        if self._round is not None and alert_payload(event) is not None:
            self._round.append(event)

    async def end_round(self) -> tuple[DeliveryResult, ...]:
        """管线结束一轮评估：把这一批一次性投递出去。"""

        pending = self._round or []
        self._round = None
        if not pending:
            return ()
        return await self.deliver_round(pending)

    async def deliver(self, event: DomainEvent) -> tuple[DeliveryResult, ...]:
        """投递单条事件；测试发送与不经过管线的调用方走这里。"""

        return await self.deliver_round((event,))

    async def deliver_round(self, events: Iterable[DomainEvent]) -> tuple[DeliveryResult, ...]:
        """一轮的告警 → 每个通道一条投递（合并窗口内被挡下的不投、不记台账）。"""

        digest = group_digest(events)
        if digest is None:
            return ()
        subscriptions = resolve_subscriptions(await asyncio.to_thread(self._subscriptions))
        # 合并窗口按这一轮告警自身的时刻算，不按墙钟：窗口比较的是市场数据间隔，
        # 补算历史事件时也不会因为「刚刚才处理」而把不同时段的两条并成一条。
        moment = digest.occurred_at
        results: list[DeliveryResult] = []
        for sink in self._active():
            subscription = subscriptions.get(sink.name)
            items = tuple(
                item
                for item in digest.items
                if subscription is None or subscription.allows(item.alert)
            )
            if not items:
                continue
            admitted: list[DigestItem] = []
            for item in items:
                count = self._window.admit(
                    (sink.name, item.instrument_id, item.type), item.count, moment
                )
                if count is None:
                    continue
                admitted.append(replace(item, count=count))
            if not admitted:
                continue
            channel_digest = DeliveryDigest(items=tuple(admitted), occurred_at=digest.occurred_at)
            result = await _deliver_one(sink, channel_digest)
            results.append(result)
            await self._recorder(result, _alert_id(channel_digest))
        return tuple(results)

    def _active(self) -> tuple[Sink, ...]:
        if self._enabled is None:
            return self._sinks
        return tuple(sink for sink in self._sinks if sink.name in self._enabled)

    async def _record_to_database(self, result: DeliveryResult, alert_id: str | None) -> None:
        await record_delivery(result, alert_id, clock=self._clock)


def build_sinks(
    *,
    channels: Iterable[str],
    broadcast: Callable[..., None],
    config: Callable[[], ChannelConfig] = _empty_config,
    subscriptions: Callable[[], Mapping[str, Any]] = _empty_subscriptions,
    clock: Clock | None = None,
    recorder: DeliveryRecorder | None = None,
) -> SinkRegistry:
    """按配置装配通道。

    清单里的名字决定初始开启哪些通道；已实现但未开启的通道也会构造出来，之后用
    `events.apply_channels` 打开即可立即生效。不认识的通道名忽略。
    """

    deps = SinkDeps(broadcast=broadcast, config=config)
    enabled = [name for name in dict.fromkeys(channels) if name in CHANNEL_BUILDERS]
    unknown = [name for name in dict.fromkeys(channels) if name not in CHANNEL_BUILDERS]
    if unknown:
        logger.warning("忽略未实现的通道: %s", ", ".join(unknown))
    registry = SinkRegistry(
        [builder(deps) for builder in CHANNEL_BUILDERS.values()],
        enabled=enabled,
        recorder=recorder,
        clock=clock,
        subscriptions=subscriptions,
    )
    return registry


async def _deliver_one(sink: Sink, digest: DeliveryDigest) -> DeliveryResult:
    """单个通道的投递：异常一律折成失败结果，好让台账记下原因。"""

    try:
        return await sink.deliver(digest)
    except Exception as exc:
        logger.exception("通道投递失败: channel=%s", sink.name)
        return DeliveryResult(channel=sink.name, status="failed", error=str(exc))


def _alert_id(digest: DeliveryDigest) -> str | None:
    """台账里的告警引用：取这一批的第一条，台账一列放不下整批。"""

    return digest.items[0].id


def _insert(values: dict[str, Any]) -> None:
    with session_scope() as session:
        session.add(NotificationDeliveryRow(**values))


def build_channel(name: str, *, config: Callable[[], ChannelConfig]) -> Sink | None:
    """按名字单独构造一个通道，给「测试发送」用；名字未实现时返回 `None`。

    这个通道不进已安装的注册表：测试消息只发一次，不改变正式投递的开关状态。
    `config` 与 `SinkDeps.config` 同一形态——「每次投递现读配置」的入口，这里直接透传，
    不再包一层，否则通道拿到的会是一个函数对象而不是配置。
    """

    builder = CHANNEL_BUILDERS.get(name)
    if builder is None:
        return None
    return builder(SinkDeps(broadcast=_discard, config=config))


async def record_delivery(
    result: DeliveryResult,
    alert_id: str | None = None,
    *,
    clock: Clock | None = None,
) -> None:
    """写一行投递台账；写失败只记录日志，不影响已经发出的推送。"""

    values: dict[str, Any] = {
        "id": "nd_" + uuid4().hex[:24],
        "channel": result.channel,
        "alert_id": alert_id,
        "status": result.status,
        "error": None if result.error is None else result.error[:2000],
        "created_at": (clock or SystemClock()).now(),
    }
    try:
        await asyncio.to_thread(_insert, values)
    except Exception:  # 台账写失败不能把已经发出去的推送判成失败
        logger.exception("投递台账写入失败: channel=%s", result.channel)


def list_deliveries(limit: int = 20) -> list[NotificationDeliveryRow]:
    """最近若干条投递台账，新的在前；条数由调用方限制，不做定期清理。"""

    with session_scope() as session:
        statement = (
            select(NotificationDeliveryRow)
            .order_by(
                NotificationDeliveryRow.created_at.desc(),
                NotificationDeliveryRow.id.desc(),
            )
            .limit(limit)
        )
        return list(session.scalars(statement))


def _discard(*_args: Any, **_kwargs: Any) -> None:
    """浏览器推送入口的占位：测试发送只针对外部通道，这里什么也不做。"""

    return None

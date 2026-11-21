"""通道注册表：按配置决定启用哪些通道，并记录每次投递。

三条约定：

- **注册只在这里**。新通道 = 实现 `Sink` + 在 `CHANNEL_BUILDERS` 加一行；
  `stream/hub.py`、`alerts/` 与所有中间件都不用改。
- **配置来自 `settings` 表**（`notifications.channels`），不在仓库里写死开关；
  不认识的通道名直接忽略，不假装支持。当前只有 `browser` 一种实现。
- **开关立即生效**。设置页保存后调用 `events.apply_channels`，装好的管线把自己的
  注册表按新清单过滤，不需要重启进程；进程启动时按同一份配置装配一次。

每次投递写一行 `notification_deliveries`（通道、告警、状态、错误、时间），时间取注入
的时钟，与项目其它模块一致。写台账失败只记录日志，不影响推送本身。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.core import Clock, SystemClock
from app.db import session_scope
from app.events.event import DomainEvent
from app.events.sinks.base import DeliveryResult, NotificationDeliveryRow, Sink
from app.events.sinks.browser import BrowserSink

__all__ = [
    "CHANNEL_BUILDERS",
    "DeliveryRecorder",
    "SinkRegistry",
    "build_sinks",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SinkDeps:
    """通道构造参数：推送入口由装配根注入。"""

    broadcast: Callable[..., None]


ChannelBuilder = Callable[[SinkDeps], Sink]
#: `(投递结果, 告警标识) -> None`：投递台账的写入方式，测试可换成内存记录。
DeliveryRecorder = Callable[[DeliveryResult, str | None], Awaitable[None]]

#: 通道注册表：配置里出现哪个名字就构造哪个通道。
CHANNEL_BUILDERS: dict[str, ChannelBuilder] = {
    "browser": lambda deps: BrowserSink(deps.broadcast),
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
    ) -> None:
        self._sinks = tuple(sinks)
        self._clock = clock or SystemClock()
        self._enabled: set[str] | None = None if enabled is None else set(enabled)
        self._recorder = recorder or self._record_to_database

    @property
    def channels(self) -> tuple[str, ...]:
        """当前启用（且已实现）的通道名。"""

        return tuple(sink.name for sink in self._active())

    def set_channels(self, channels: Iterable[str]) -> None:
        """按新的开关清单过滤；不在清单里的通道立即停止投递。"""

        self._enabled = set(channels)

    def accepts(self, event: DomainEvent) -> bool:
        return any(sink.accepts(event) for sink in self._active())

    async def deliver(self, event: DomainEvent) -> tuple[DeliveryResult, ...]:
        """投递到所有启用且接收这类事件的通道，并逐条记录结果。"""

        alert_id = _alert_id(event)
        results: list[DeliveryResult] = []
        for sink in self._active():
            if not sink.accepts(event):
                continue
            result = await _deliver_one(sink, event)
            results.append(result)
            await self._recorder(result, alert_id)
        return tuple(results)

    def _active(self) -> tuple[Sink, ...]:
        if self._enabled is None:
            return self._sinks
        return tuple(sink for sink in self._sinks if sink.name in self._enabled)

    async def _record_to_database(self, result: DeliveryResult, alert_id: str | None) -> None:
        values: dict[str, Any] = {
            "id": "nd_" + uuid4().hex[:24],
            "channel": result.channel,
            "alert_id": alert_id,
            "status": result.status,
            "error": None if result.error is None else result.error[:2000],
            "created_at": self._clock.now(),
        }
        try:
            await asyncio.to_thread(_insert, values)
        except Exception:  # 台账写失败不能把已经发出去的推送判成失败
            logger.exception("投递台账写入失败: channel=%s", result.channel)


def build_sinks(
    *,
    channels: Iterable[str],
    broadcast: Callable[..., None],
    clock: Clock | None = None,
    recorder: DeliveryRecorder | None = None,
) -> SinkRegistry:
    """按配置装配通道。

    清单里的名字决定初始开启哪些通道；已实现但未开启的通道也会构造出来，之后用
    `events.apply_channels` 打开即可立即生效。不认识的通道名忽略（当前只有 browser
    一种实现）。
    """

    deps = SinkDeps(broadcast=broadcast)
    enabled = [name for name in dict.fromkeys(channels) if name in CHANNEL_BUILDERS]
    unknown = [name for name in dict.fromkeys(channels) if name not in CHANNEL_BUILDERS]
    if unknown:
        logger.warning("忽略未实现的通道: %s", ", ".join(unknown))
    registry = SinkRegistry(
        [builder(deps) for builder in CHANNEL_BUILDERS.values()],
        enabled=enabled,
        recorder=recorder,
        clock=clock,
    )
    return registry


async def _deliver_one(sink: Sink, event: DomainEvent) -> DeliveryResult:
    """单个通道的投递：异常一律折成失败结果，好让台账记下原因。"""

    try:
        return await sink.deliver(event)
    except Exception as exc:
        logger.exception("通道投递失败: channel=%s", sink.name)
        return DeliveryResult(channel=sink.name, status="failed", error=str(exc))


def _alert_id(event: DomainEvent) -> str | None:
    alert = event.payload.get("alert")
    if not isinstance(alert, dict):
        return None
    value = alert.get("id")
    return value if isinstance(value, str) else None


def _insert(values: dict[str, Any]) -> None:
    with session_scope() as session:
        session.add(NotificationDeliveryRow(**values))

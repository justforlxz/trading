"""事件管线的组装与洋葱执行。

中间件签名固定为 `async def mw(event, call_next) -> None`：不调用 `call_next` 即中止
链路，调用前后都可以处理（洋葱）。`DEFAULT_MIDDLEWARES` 是**唯一**的注册表——新增
能力时在它下面加一行，不改 `stream/hub.py`，也不改 `alerts/`。

链路的末端不是通道本身：`route` 按通道声明的订阅过滤，再交给通道投递；没有通道接收
就中止，不产生投递记录。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from app.events.event import DomainEvent
from app.events.middlewares import dedupe, normalize, route, rule_engine
from app.events.sinks.registry import SinkRegistry

__all__ = [
    "DEFAULT_MIDDLEWARES",
    "Middleware",
    "MiddlewareFactory",
    "Pipeline",
    "PipelineDeps",
    "build_pipeline",
]

logger = logging.getLogger(__name__)

CallNext = Callable[[DomainEvent], Awaitable[None]]
Middleware = Callable[[DomainEvent, CallNext], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class PipelineDeps:
    """中间件工厂拿到的依赖：通道注册表。"""

    sinks: SinkRegistry


MiddlewareFactory = Callable[[PipelineDeps], Middleware]

#: 中间件注册表：顺序即执行顺序（外层在前）。新能力在这里加一行。
DEFAULT_MIDDLEWARES: tuple[MiddlewareFactory, ...] = (
    normalize.middleware,
    rule_engine.middleware,
    dedupe.middleware,
    route.middleware,
)


class Pipeline:
    """按注册顺序把一条事件穿过全部中间件，并持有自己的通道注册表。"""

    def __init__(
        self,
        middlewares: Sequence[Middleware],
        *,
        sinks: SinkRegistry | None = None,
    ) -> None:
        self._middlewares = tuple(middlewares)
        self._sinks = sinks

    def apply_channels(self, channels: Sequence[str]) -> None:
        """通道开关变化：只影响本管线自己的注册表，没有注册表时什么也不做。"""

        if self._sinks is not None:
            self._sinks.set_channels(channels)

    async def run(self, event: DomainEvent) -> None:
        """处理一条事件；链路上任何异常只记录，不向调用方抛出。"""

        try:
            await self._dispatch(event, 0)
        except Exception:
            logger.exception("事件处理失败: kind=%s inst=%s", event.kind, event.inst_id)

    async def _dispatch(self, event: DomainEvent, index: int) -> None:
        if index >= len(self._middlewares):
            return
        call_next: CallNext = lambda next_event: self._dispatch(next_event, index + 1)  # noqa: E731
        await self._middlewares[index](event, call_next)


def build_pipeline(
    *,
    sinks: SinkRegistry,
    middlewares: Sequence[MiddlewareFactory] = DEFAULT_MIDDLEWARES,
) -> Pipeline:
    """按注册表实例化管线；每个中间件工厂拿到同一份依赖。"""

    deps = PipelineDeps(sinks=sinks)
    return Pipeline([factory(deps) for factory in middlewares], sinks=sinks)

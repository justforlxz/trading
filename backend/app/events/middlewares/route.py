"""按通道订阅过滤：只有声明接收这类事件的通道才拿到投递。

过滤规则由通道自己给出（`Sink.accepts`），本层不猜。没有通道接收就中止链路：
不写投递记录，也不继续往后走——后面已经没有别的东西了。

新增通道不需要改本文件：在 `sinks/registry.py` 里登记实现即可。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.events.event import DomainEvent

if TYPE_CHECKING:
    from app.events.pipeline import CallNext, Middleware, PipelineDeps

__all__ = ["middleware"]


def middleware(deps: PipelineDeps) -> Middleware:
    async def route(event: DomainEvent, call_next: CallNext) -> None:
        if not deps.sinks.accepts(event):
            return
        await deps.sinks.deliver(event)
        await call_next(event)

    return route

"""把告警收进本轮批次：投递发生在轮次结束时，由通道注册表统一做。

一轮评估指一次 `Pipeline.run`：一条行情或一根收盘 K 线穿过管线，途中产出的全部告警
都属于同一轮。本层只负责收集，不做判断——订阅过滤、合并（同标的同类型合并、10 分钟
窗口）、渲染与台账都在 `events.sinks` 里，通道自己也不再各写一套。

没有通道接收这类告警（类型不在订阅里、或严重度低于门槛）时，注册表不投递、不写台账；
本层与注册表都不猜「该不该报」，只按配置放行或挡下。

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
        deps.sinks.collect(event)
        await call_next(event)

    return route

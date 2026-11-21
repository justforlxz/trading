"""同步的事件入口：调用方不等结果，事件进入队列由唯一的消费者按顺序跑完。

`emit` 是**全项目唯一**的推送入口。上游推送发生在事件循环线程里，业务包的回调可能
在其他线程里，所以统一用 `call_soon_threadsafe` 把事件放进队列。

队列 + 单个消费者任务（而不是每条事件起一个任务）是有意的：

- **顺序确定**。同一标的的两笔推送必须按到达顺序处理，否则「越界 → 回落」可能乱序，
  回落先跑、越界后跑，提醒就留在待处理里不再关闭。
- **不产生周期动作**。消费者只在队列有事件时醒来，队列空了就等；没有任何定时器。
- 高频行情只占队列一个位置的处理时间，不会为每笔推送制造一个任务。

没有安装管线时 `emit` 什么也不做——推送层不需要知道有没有订阅方。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from app.events.event import DomainEvent
from app.events.pipeline import Pipeline

__all__ = ["apply_channels", "emit", "install", "uninstall"]

logger = logging.getLogger(__name__)

_pipeline: Pipeline | None = None
_loop: asyncio.AbstractEventLoop | None = None
_queue: asyncio.Queue[DomainEvent] | None = None
_worker: asyncio.Task[None] | None = None


def install(pipeline: Pipeline, *, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """装配根在应用启动时安装管线；`loop` 缺省取当前正在跑的循环。"""

    global _pipeline, _loop, _queue, _worker
    _stop_worker()
    _pipeline = pipeline
    _loop = loop or asyncio.get_running_loop()
    _queue = asyncio.Queue()
    _worker = _loop.create_task(_consume(_pipeline, _queue), name="trading-event-worker")


def uninstall() -> None:
    """应用退出或测试收尾：停止消费者，丢弃队列与循环引用。"""

    global _pipeline, _loop, _queue
    _stop_worker()
    _pipeline = None
    _loop = None
    _queue = None


def apply_channels(channels: Sequence[str]) -> None:
    """通道开关变化：交给已安装的管线，没有安装时什么也不做。"""

    pipeline = _pipeline
    if pipeline is not None:
        pipeline.apply_channels(channels)


def emit(event: DomainEvent) -> None:
    """提交一条事件；没有安装管线、或循环已关闭时静默丢弃。"""

    queue = _queue
    loop = _loop
    if queue is None or loop is None or loop.is_closed():
        return
    try:
        loop.call_soon_threadsafe(queue.put_nowait, event)
    except RuntimeError:  # 循环在检查之后关闭：丢弃，不影响调用方
        logger.debug("事件循环已关闭，丢弃事件: kind=%s", event.kind)


async def _consume(pipeline: Pipeline, queue: asyncio.Queue[DomainEvent]) -> None:
    """唯一的消费者：按到达顺序逐条处理，处理完一条才取下一件。"""

    while True:
        event = await queue.get()
        try:
            await pipeline.run(event)
        except asyncio.CancelledError:
            raise
        except Exception:  # 单条事件失败不能拖垮消费者
            logger.exception("事件处理失败: kind=%s inst=%s", event.kind, event.inst_id)
        finally:
            queue.task_done()


def _stop_worker() -> None:
    global _worker
    worker = _worker
    _worker = None
    if worker is not None and not worker.done():
        worker.cancel()

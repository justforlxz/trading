"""scheduler 入口：`python -m app.jobs.scheduler`（Compose `scheduler` 服务）。

职责边界（`docs/architecture/overview.md` §5）：只投递任务与写心跳，**不做重计算**。
SQLAlchemy/httpx 之类的重活属于 worker。S2 尚无业务 cron，这里只维护存活心跳；
S3 起把 `sync_instruments` / `ingest_candles` 等投递函数挂到 `tick()` 里。
"""

import asyncio
import contextlib
import logging
import signal
import time
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis

from app.config import get_settings
from app.jobs.queue import enqueue_task
from app.jobs.schedule import SCHEDULE_KEY_PREFIX, PeriodicTask, build_schedule

logger = logging.getLogger(__name__)

HEARTBEAT_KEY = "trading:ops:scheduler:heartbeat"


async def tick(
    redis: Redis,
    timeout_seconds: float,
    *,
    schedule: list[PeriodicTask] | None = None,
    enqueue: Callable[[str], Awaitable[object]] | None = None,
) -> None:
    """一次调度周期：写心跳，并把到期的周期任务投递出去。

    到期判定用 `SET NX EX`，间隔即租约；投递失败会释放租约，下个心跳重试。
    """

    await redis.set(HEARTBEAT_KEY, int(time.time()), ex=int(timeout_seconds * 2))
    tasks = schedule if schedule is not None else build_schedule()
    dispatch = enqueue if enqueue is not None else _enqueue_default
    for task in tasks:
        key = f"{SCHEDULE_KEY_PREFIX}{task.name}"
        acquired = await redis.set(key, "1", nx=True, ex=max(task.interval_seconds, 1))
        if not acquired:
            continue
        try:
            await dispatch(task.task_name)
        except Exception:
            logger.exception("failed to enqueue %s; releasing lease", task.task_name)
            await redis.delete(key)


async def _enqueue_default(task_name: str) -> object:
    return await enqueue_task(task_name)


async def run() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    redis = Redis.from_url(settings.redis_url)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    logger.info("scheduler started: interval=%ss", settings.scheduler_heartbeat_interval_seconds)
    try:
        while not stop.is_set():
            try:
                await tick(redis, settings.scheduler_heartbeat_timeout_seconds)
            except Exception:
                logger.exception("scheduler tick failed; will retry on next interval")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    stop.wait(), timeout=settings.scheduler_heartbeat_interval_seconds
                )
    finally:
        await redis.aclose()
        logger.info("scheduler stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()

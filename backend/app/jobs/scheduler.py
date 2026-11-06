"""scheduler 入口：`python -m app.jobs.scheduler`（Compose `scheduler` 服务）。

职责边界（`docs/architecture/overview.md` §5）：只创建任务账本、投递任务与写心跳，
**不做重计算**。SQLAlchemy/httpx 之类的重活属于 worker。

每个到期任务都会先写一行 `ops.job_run`（`scheduled_at` 参与 job_key，因此每轮唯一），
再把 `run_id` 传给 worker；worker 负责 running → ok/partial/failed 的落库。
周期采集是唯一的生产入口，没有账本就无法回答「本轮采集成败/延迟」。
"""

import asyncio
import contextlib
import logging
import signal
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from redis.asyncio import Redis

from app.config import get_settings
from app.db.session import session_factory
from app.jobs import runs
from app.jobs.queue import enqueue_task
from app.jobs.schedule import SCHEDULE_KEY_PREFIX, PeriodicTask, build_schedule

logger = logging.getLogger(__name__)

HEARTBEAT_KEY = "trading:ops:scheduler:heartbeat"


async def tick(
    redis: Redis,
    timeout_seconds: float,
    *,
    schedule: list[PeriodicTask] | None = None,
    enqueue: Callable[[str, int | None], Awaitable[object]] | None = None,
    start_run: Callable[[str], Awaitable[int | None]] | None = None,
    fail_run: Callable[[int, str], Awaitable[None]] | None = None,
) -> None:
    """一次调度周期：写心跳，把到期任务写入账本并投递。

    到期判定用 `SET NX EX`，间隔即租约；投递失败会释放租约并让账本落 `failed`。
    """

    await redis.set(HEARTBEAT_KEY, int(time.time()), ex=int(timeout_seconds * 2))
    tasks = schedule if schedule is not None else build_schedule()
    dispatch = enqueue if enqueue is not None else _enqueue_default
    starter = start_run if start_run is not None else _start_run_default
    failer = fail_run if fail_run is not None else _fail_run_default
    for task in tasks:
        key = f"{SCHEDULE_KEY_PREFIX}{task.name}"
        acquired = await redis.set(key, "1", nx=True, ex=max(task.interval_seconds, 1))
        if not acquired:
            continue
        try:
            run_id = await starter(task.task_name)
        except Exception:
            logger.exception("failed to create job run for %s; enqueue anyway", task.task_name)
            run_id = None
        try:
            await dispatch(task.task_name, run_id)
        except Exception as error:
            logger.exception("failed to enqueue %s; releasing lease", task.task_name)
            await redis.delete(key)
            if run_id is not None:
                await failer(run_id, str(error))


async def _start_run_default(task_name: str) -> int | None:
    async with session_factory() as session:
        run, _ = await runs.create_run(
            session,
            job_name=task_name,
            payload={"task": task_name, "scheduled_at": datetime.now(tz=UTC).isoformat()},
        )
        return run.id


async def _fail_run_default(run_id: int, error: str) -> None:
    async with session_factory() as session:
        await runs.finish_run(session, run_id, "failed", error=error)


async def _enqueue_default(task_name: str, run_id: int | None) -> object:
    return await enqueue_task(task_name, run_id=run_id)


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

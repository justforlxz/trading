"""arq 连接池与入队封装：API 与 scheduler 共用同一份连接。

只负责「投递」，不执行任务；执行体的状态收敛见 `app.jobs.tasks`。
"""

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import get_settings

_pool: ArqRedis | None = None


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _pool


async def enqueue_task(task_name: str, **kwargs: object) -> str | None:
    """投递任务；arq 返回自己的 job id（与 `ops.job_run.id` 不是同一个）。"""

    pool = await get_pool()
    job = await pool.enqueue_job(task_name, **kwargs)
    return None if job is None else job.job_id


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


__all__ = ["close_pool", "enqueue_task", "get_pool"]

"""`ops.job_run` 生命周期：入队去重、状态迁移与查询。

唯一的幂等键是 `(job_name, job_key)`；同一组参数的重复请求不会再产生新行，
而是返回已有任务（`created=False`），由调用方决定回 202 还是 200。
`failed` / `partial` 的任务允许用同键重试：复用原行并重置为 `queued`。
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.keys import canonical_job_key, canonical_payload
from app.ops.models import JobRun

RUNNING_STATUSES = ("queued", "running")
RETRYABLE_STATUSES = ("failed", "partial")


async def create_run(
    session: AsyncSession, *, job_name: str, payload: dict[str, Any] | None = None
) -> tuple[JobRun, bool]:
    """登记一次任务；已存在同键任务时返回旧行且 `created=False`。"""

    job_key = canonical_job_key(job_name, payload)
    statement = (
        pg_insert(JobRun)
        .values(
            job_name=job_name,
            job_key=job_key,
            status="queued",
            attempts=0,
            scheduled_at=datetime.now(tz=UTC),
            payload_hash=canonical_payload(payload),
        )
        .on_conflict_do_nothing(constraint="uq_job_run_key")
        .returning(JobRun.id)
    )
    created_id = await session.scalar(statement)
    await session.commit()
    if created_id is not None:
        run = await session.get(JobRun, created_id)
        if run is None:  # pragma: no cover - 刚写入必然存在
            raise RuntimeError("job run lost after insert")
        return run, True

    existing = await session.scalar(
        select(JobRun).where(JobRun.job_name == job_name, JobRun.job_key == job_key)
    )
    if existing is None:  # pragma: no cover - 冲突必然有行
        raise RuntimeError("job run conflict without row")
    if existing.status not in RETRYABLE_STATUSES:
        return existing, False
    # 失败/部分失败允许同参数重试：复用同一行，避免永久锁死。
    existing.status = "queued"
    existing.scheduled_at = datetime.now(tz=UTC)
    existing.started_at = None
    existing.finished_at = None
    existing.error = None
    existing.result = {}
    await session.commit()
    return existing, True


async def mark_running(session: AsyncSession, run_id: int) -> None:
    run = await session.get(JobRun, run_id)
    if run is None:
        return
    run.status = "running"
    run.started_at = datetime.now(tz=UTC)
    run.attempts = (run.attempts or 0) + 1
    await session.commit()


async def finish_run(
    session: AsyncSession,
    run_id: int,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    if status not in {"ok", "partial", "failed", "skipped"}:
        raise ValueError(f"invalid final status: {status}")
    run = await session.get(JobRun, run_id)
    if run is None:
        return
    run.status = status
    run.finished_at = datetime.now(tz=UTC)
    run.result = result or {}
    run.error = error
    await session.commit()


async def get_run(session: AsyncSession, run_id: int) -> JobRun | None:
    return await session.get(JobRun, run_id)


async def list_runs(
    session: AsyncSession,
    *,
    job_name: str | None = None,
    status: str | None = None,
    limit: int = 50,
    cursor: int | None = None,
) -> tuple[list[JobRun], int | None]:
    statement = select(JobRun).order_by(JobRun.id.desc()).limit(limit + 1)
    if job_name:
        statement = statement.where(JobRun.job_name == job_name)
    if status:
        statement = statement.where(JobRun.status == status)
    if cursor is not None:
        statement = statement.where(JobRun.id < cursor)
    rows = list(await session.scalars(statement))
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return rows[:limit], next_cursor


__all__ = [
    "RETRYABLE_STATUSES",
    "RUNNING_STATUSES",
    "create_run",
    "finish_run",
    "get_run",
    "list_runs",
    "mark_running",
]

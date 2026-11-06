"""`/api/v1/ops/*`：任务运行记录查询（长任务的落点）。"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.v1.deps import session_dep
from app.jobs.runs import get_run, list_runs
from app.ops.models import JobRun

router = APIRouter(prefix="/ops", tags=["ops"])


def job_payload(row: JobRun) -> dict[str, Any]:
    def iso(value):
        return None if value is None else value.isoformat()

    return {
        "id": row.id,
        "job_name": row.job_name,
        "job_key": row.job_key,
        "status": row.status,
        "attempts": row.attempts,
        "scheduled_at": iso(row.scheduled_at),
        "started_at": iso(row.started_at),
        "finished_at": iso(row.finished_at),
        "worker": row.worker,
        "error": row.error,
        "result": row.result,
    }


@router.get("/job-runs")
async def list_job_runs(
    session: AsyncSession = Depends(session_dep),
    job_name: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: int | None = None,
) -> dict[str, Any]:
    rows, next_cursor = await list_runs(
        session, job_name=job_name, status=status, limit=limit, cursor=cursor
    )
    return {"items": [job_payload(row) for row in rows], "next_cursor": next_cursor}


@router.get("/job-runs/{run_id}")
async def get_job_run(run_id: int, session: AsyncSession = Depends(session_dep)) -> dict[str, Any]:
    row = await get_run(session, run_id)
    if row is None:
        raise ApiError("JOB_NOT_FOUND", f"unknown job run: {run_id}", status_code=404)
    return job_payload(row)


__all__ = ["job_payload", "router"]

"""外部数据同步任务：任务流水、最后成功时间与健康读取。

每次同步先写一行 `running`，结束时改成 `succeeded` 或 `failed`。健康接口只读这张
表，不在请求里临时探测上游；最后成功时间取最近一次成功任务的 `finished_at`。

单进程部署没有独立 worker：同步在请求线程内同步执行，任务表记录的仍是真实起止时间。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select

from app.core import Clock, SystemClock, ValidationError
from app.db import session_scope
from app.market.model import DataSyncJobRow

__all__ = [
    "SYNC_STATUSES",
    "ProviderSyncStatus",
    "QueueSyncStatus",
    "SyncJobView",
    "finish_sync_job",
    "latest_success_at",
    "latest_sync_job",
    "provider_sync_status",
    "queue_sync_status",
    "start_sync_job",
    "sync_summary",
]

SYNC_STATUSES = ("running", "succeeded", "failed")
STUCK_AFTER = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class SyncJobView:
    id: str
    provider: str
    dataset: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    #: `market_overview` 的同步游标记录本次报价的最新时间（ISO 8601）；其他数据集为空。
    cursor: str | None
    rows: int
    error: str | None
    last_success_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProviderSyncStatus:
    provider: str
    dataset: str | None
    status: str
    last_success_at: datetime | None
    error: str | None
    failure_count: int
    #: 最近一条任务的状态；没有任务记录时为 `None`。健康接口据此写真实 detail。
    job_status: str | None = None
    #: 最近一次成功同步写入的报价时间；没有记录时为 `None`。
    data_as_of: datetime | None = None


@dataclass(frozen=True, slots=True)
class QueueSyncStatus:
    status: str
    running: int
    stuck: int
    failed: int
    last_success_at: datetime | None
    error: str | None


def _view(row: DataSyncJobRow) -> SyncJobView:
    return SyncJobView(
        id=row.id,
        provider=row.provider,
        dataset=row.dataset,
        status=row.status,
        started_at=row.started_at,
        finished_at=row.finished_at,
        cursor=row.cursor,
        rows=row.rows,
        error=row.error,
        last_success_at=row.last_success_at,
    )


def start_sync_job(
    provider: str,
    dataset: str,
    *,
    clock: Clock | None = None,
) -> SyncJobView:
    """写一条 running 任务；`provider` 与 `dataset` 都必须是调用方给定的事实。"""

    name = provider.strip()
    data = dataset.strip()
    if not name:
        raise ValidationError("provider 不能为空")
    if not data:
        raise ValidationError("dataset 不能为空")
    moment = (clock or SystemClock()).now()
    row = DataSyncJobRow(
        id="job_" + uuid4().hex[:24],
        provider=name,
        dataset=data,
        status="running",
        started_at=moment,
        finished_at=None,
        cursor=None,
        rows=0,
        error=None,
        last_success_at=None,
    )
    with session_scope() as session:
        session.add(row)
        session.flush()
    return _view(row)


def finish_sync_job(
    job_id: str,
    status: str,
    *,
    rows: int = 0,
    error: str | None = None,
    cursor: str | None = None,
    clock: Clock | None = None,
) -> SyncJobView:
    """结束一条任务；成功时把结束时刻同时记为最后成功时间。"""

    if status not in ("succeeded", "failed"):
        raise ValidationError(f"未知任务状态 {status!r}")
    if rows < 0:
        raise ValidationError("rows 不能为负数")
    moment = (clock or SystemClock()).now()
    with session_scope() as session:
        row = session.get(DataSyncJobRow, job_id)
        if row is None:
            raise ValidationError(f"同步任务不存在: {job_id}")
        row.status = status
        row.finished_at = moment
        row.rows = rows
        row.error = error
        row.cursor = cursor
        if status == "succeeded":
            row.last_success_at = moment
        session.flush()
        return _view(row)


def latest_sync_job(
    *, provider: str | None = None, dataset: str | None = None
) -> SyncJobView | None:
    """最近一条任务；可按 provider 与 dataset 收窄。"""

    statement = select(DataSyncJobRow)
    if provider is not None:
        statement = statement.where(DataSyncJobRow.provider == provider)
    if dataset is not None:
        statement = statement.where(DataSyncJobRow.dataset == dataset)
    statement = statement.order_by(DataSyncJobRow.started_at.desc()).limit(1)
    with session_scope() as session:
        row = session.scalar(statement)
    return None if row is None else _view(row)


def latest_success_at(
    *, provider: str | None = None, dataset: str | None = None
) -> datetime | None:
    """最近一次成功任务的结束时间；没有成功过就是 `None`。"""

    statement = select(func.max(DataSyncJobRow.finished_at)).where(
        DataSyncJobRow.status == "succeeded"
    )
    if provider is not None:
        statement = statement.where(DataSyncJobRow.provider == provider)
    if dataset is not None:
        statement = statement.where(DataSyncJobRow.dataset == dataset)
    with session_scope() as session:
        return session.scalar(statement)


def sync_summary(provider: str, dataset: str | None = None) -> tuple[datetime | None, int]:
    """数据源状态：最近同步时间与失败任务数。

    传入 `dataset` 时，最近同步时间只统计该数据集；失败次数仍按 Provider 累计。
    健康接口必须传数据集，否则一个数据集的成功会掩盖另一个数据集的陈旧。
    """

    statement = select(func.max(DataSyncJobRow.finished_at)).where(
        DataSyncJobRow.provider == provider,
        DataSyncJobRow.status == "succeeded",
    )
    if dataset is not None:
        statement = statement.where(DataSyncJobRow.dataset == dataset)
    failures = (
        select(func.count())
        .select_from(DataSyncJobRow)
        .where(
            DataSyncJobRow.provider == provider,
            DataSyncJobRow.status == "failed",
        )
    )
    with session_scope() as session:
        return session.scalar(statement), int(session.scalar(failures) or 0)


def _parse_data_as_of(value: str | None) -> datetime | None:
    """同步游标里的报价时间；无法解析或没有记录时如实返回 `None`。"""

    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def provider_sync_status(
    provider: str,
    dataset: str | None = None,
    *,
    now: datetime | None = None,
    stale_after: timedelta | None = None,
) -> ProviderSyncStatus:
    """某个 Provider 的同步状态；失败次数是历史累计。

    只有「最近一次任务成功，并且最后成功时间仍在 `stale_after` 以内」才是 `ok`。
    `running` 表示结果尚未确认，同样按 `stale` 报告；成功过但超过时效时也返回
    `stale`，避免把旧数据当成最新值。
    """

    job = latest_sync_job(provider=provider, dataset=dataset)
    last_success, failures = sync_summary(provider, dataset)
    data_as_of = _parse_data_as_of(None if job is None else job.cursor)
    if job is None:
        return ProviderSyncStatus(
            provider=provider,
            dataset=dataset,
            status="unconfigured",
            last_success_at=last_success,
            error=None,
            failure_count=failures,
            data_as_of=data_as_of,
        )
    if job.status == "running":
        return ProviderSyncStatus(
            provider=provider,
            dataset=dataset,
            status="stale",
            last_success_at=last_success,
            error=None,
            failure_count=failures,
            job_status="running",
            data_as_of=data_as_of,
        )
    if job.status == "failed":
        return ProviderSyncStatus(
            provider=provider,
            dataset=dataset,
            status="stale",
            last_success_at=last_success,
            error=job.error,
            failure_count=failures,
            job_status="failed",
            data_as_of=data_as_of,
        )
    moment = now or SystemClock().now()
    # 没有最后成功时间就无法证明数据新鲜，同样按过期处理。
    expired = stale_after is not None and (
        last_success is None or last_success < moment - stale_after
    )
    return ProviderSyncStatus(
        provider=provider,
        dataset=dataset,
        status="stale" if expired else "ok",
        last_success_at=last_success,
        error=None,
        failure_count=failures,
        job_status="succeeded",
        data_as_of=data_as_of,
    )


def queue_sync_status(*, clock: Clock | None = None) -> QueueSyncStatus:
    """进程内同步队列状态：卡住的 running 任务与尚未恢复的失败。

    `data_sync_jobs` 只追加、不清理，因此失败记录要跟最近一次成功比较：只有失败发生在
    最近一次成功之后，才说明当前状态没有恢复。否则一次旧失败会让健康检查永远降级。
    """

    moment = (clock or SystemClock()).now()
    with session_scope() as session:
        running_rows = list(
            session.scalars(select(DataSyncJobRow).where(DataSyncJobRow.status == "running"))
        )
        last_success = session.scalar(
            select(func.max(DataSyncJobRow.finished_at)).where(DataSyncJobRow.status == "succeeded")
        )
        failure_statement = select(DataSyncJobRow).where(DataSyncJobRow.status == "failed")
        if last_success is not None:
            failure_statement = failure_statement.where(
                func.coalesce(DataSyncJobRow.finished_at, DataSyncJobRow.started_at) > last_success
            )
        failures = list(
            session.scalars(
                failure_statement.order_by(
                    func.coalesce(DataSyncJobRow.finished_at, DataSyncJobRow.started_at).desc()
                )
            )
        )
    stuck = sum(1 for row in running_rows if row.started_at <= moment - STUCK_AFTER)
    if stuck:
        return QueueSyncStatus(
            status="stale",
            running=len(running_rows),
            stuck=stuck,
            failed=len(failures),
            last_success_at=last_success,
            error=f"{stuck} 个同步任务超过 30 分钟仍在运行",
        )
    if failures:
        return QueueSyncStatus(
            status="stale",
            running=len(running_rows),
            stuck=0,
            failed=len(failures),
            last_success_at=last_success,
            error=failures[0].error,
        )
    return QueueSyncStatus(
        status="ok",
        running=len(running_rows),
        stuck=0,
        failed=0,
        last_success_at=last_success,
        error=None,
    )

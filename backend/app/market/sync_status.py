"""采集账本（`market.data_source_sync`）与 `/market/sync-status` 聚合。

每次采集按「源 × 数据集 × scope × 窗口」写一行：成功刷新 `last_success_at`，
失败保留 `last_error`。`/sync-status` 取每个组合的最新一行，并按数据集阈值
判定 `stale`，回答 P1-05「采集延迟」是否超预期。
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.market.models import DataSourceSync

SOURCE_OKX = "okx"
SOURCE_YAHOO = "yahoo"

DATASET_INSTRUMENTS = "market.instrument"
DATASET_CANDLE = "market.candle"
DATASET_EQUITY = "market.equity_candle"

SYNC_STATUSES = ("running", "ok", "partial", "failed")


def day_bucket(moment: datetime) -> tuple[datetime, datetime]:
    """周期采集账本按自然日聚合，避免每分钟一行把账本撑爆。"""

    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


async def record_sync(
    session: AsyncSession,
    *,
    source: str,
    dataset: str,
    scope: str,
    window_start: datetime,
    window_end: datetime,
    status: str,
    rows_written: int = 0,
    error: str | None = None,
    coverage: dict[str, Any] | None = None,
) -> DataSourceSync:
    """写入或刷新一行采集账本（不 commit，调用方决定事务边界）。"""

    if status not in SYNC_STATUSES:
        raise ValueError(f"unknown sync status: {status}")
    now = datetime.now(tz=UTC)
    statement = pg_insert(DataSourceSync).values(
        source=source,
        dataset=dataset,
        scope=scope,
        window_start=window_start,
        window_end=window_end,
        status=status,
        attempts=1,
        rows_written=rows_written,
        last_error=error,
        last_success_at=now if status == "ok" else None,
        coverage=coverage or {},
        updated_at=now,
    )
    statement = statement.on_conflict_do_update(
        constraint="uq_data_source_sync",
        set_={
            "status": statement.excluded.status,
            "attempts": DataSourceSync.attempts + 1,
            "rows_written": statement.excluded.rows_written,
            "last_error": statement.excluded.last_error,
            "last_success_at": (
                statement.excluded.last_success_at
                if status == "ok"
                else DataSourceSync.last_success_at
            ),
            "coverage": statement.excluded.coverage,
            "updated_at": statement.excluded.updated_at,
        },
    ).returning(DataSourceSync)
    return (await session.scalars(statement)).one()


async def list_sync_status(
    session: AsyncSession,
    *,
    stale_after_seconds: dict[str, int] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """每个 (source, dataset, scope) 的最新状态，附 `stale` 与 `age_seconds`。"""

    moment = now or datetime.now(tz=UTC)
    thresholds = stale_after_seconds or {}
    statement = (
        select(DataSourceSync)
        .order_by(
            DataSourceSync.source,
            DataSourceSync.dataset,
            DataSourceSync.scope,
            DataSourceSync.window_end.desc(),
        )
        .distinct(DataSourceSync.source, DataSourceSync.dataset, DataSourceSync.scope)
    )
    rows = list(await session.scalars(statement))
    items: list[dict[str, Any]] = []
    for row in rows:
        # 年龄以「上次成功」为准；从未成功时退回「上次尝试」，避免用未来/历史窗口
        # 当参照：day_bucket 的 window_end 是明天 00:00Z，用它会出现负年龄。
        reference = row.last_success_at or row.updated_at
        age_seconds = max(0, int((moment - reference).total_seconds()))
        threshold = thresholds.get(row.dataset)
        if row.status == "failed":
            # 本轮失败：即使刚尝试过，数据也不可信，直接计入 stale。
            stale = True
        elif threshold is None:
            stale = True
        else:
            stale = age_seconds > threshold
        items.append(
            {
                "source": row.source,
                "dataset": row.dataset,
                "scope": row.scope,
                "status": row.status,
                "window_start": row.window_start.isoformat(),
                "window_end": row.window_end.isoformat(),
                "last_success_at": (
                    None if row.last_success_at is None else row.last_success_at.isoformat()
                ),
                "updated_at": row.updated_at.isoformat(),
                "rows_written": row.rows_written,
                "last_error": row.last_error,
                "age_seconds": age_seconds,
                "stale": stale,
            }
        )
    items.sort(key=lambda item: (item["source"], item["dataset"], item["scope"]))
    return items


__all__ = [
    "DATASET_CANDLE",
    "DATASET_EQUITY",
    "DATASET_INSTRUMENTS",
    "SOURCE_OKX",
    "SOURCE_YAHOO",
    "day_bucket",
    "list_sync_status",
    "record_sync",
]

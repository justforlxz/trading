"""周期调度表：任务名、执行体与最小间隔。

scheduler 每个心跳只做两件事：写心跳、把到期的任务投递出去。是否到期用
Redis `SET NX EX` 判定，因此多副本 scheduler 同时运行也不会重复投递。
"""

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.jobs import tasks

SCHEDULE_KEY_PREFIX = "trading:ops:schedule:"


@dataclass(frozen=True, slots=True)
class PeriodicTask:
    name: str
    task_name: str
    interval_seconds: int


def build_schedule(settings: Settings | None = None) -> list[PeriodicTask]:
    current = settings or get_settings()
    return [
        PeriodicTask(
            tasks.SYNC_INSTRUMENTS,
            tasks.SYNC_INSTRUMENTS,
            current.sync_instruments_interval_seconds,
        ),
        PeriodicTask(
            tasks.INGEST_CANDLES, tasks.INGEST_CANDLES, current.ingest_candles_interval_seconds
        ),
        PeriodicTask(tasks.SYNC_EQUITY, tasks.SYNC_EQUITY, current.sync_equity_interval_seconds),
        PeriodicTask(tasks.QUALITY_SCAN, tasks.QUALITY_SCAN, current.quality_interval_seconds),
        PeriodicTask(
            tasks.SYNC_SESSIONS, tasks.SYNC_SESSIONS, current.sync_sessions_interval_seconds
        ),
        PeriodicTask(
            tasks.SCAN_OPPORTUNITIES,
            tasks.SCAN_OPPORTUNITIES,
            current.opportunity_scan_interval_seconds,
        ),
        PeriodicTask(tasks.PURGE_ROLLING, tasks.PURGE_ROLLING, current.retention_interval_seconds),
    ]


__all__ = ["SCHEDULE_KEY_PREFIX", "PeriodicTask", "build_schedule"]

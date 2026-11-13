"""每日权益快照的调度口径：北京时间零点与可立即停止的守护线程。"""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Event
from zoneinfo import ZoneInfo

from app.jobs import next_beijing_midnight, start_equity_snapshot_scheduler

BEIJING = ZoneInfo("Asia/Shanghai")


def test_next_beijing_midnight_moves_to_the_next_day_after_midnight() -> None:
    now = datetime(2026, 11, 13, 0, 0, 0, tzinfo=BEIJING)

    target = next_beijing_midnight(now)

    assert target == datetime(2026, 11, 14, 0, 0, 0, tzinfo=BEIJING)


def test_next_beijing_midnight_from_the_previous_afternoon() -> None:
    now = datetime(2026, 11, 13, 15, 30, tzinfo=BEIJING)

    target = next_beijing_midnight(now)

    assert target == datetime(2026, 11, 14, 0, 0, 0, tzinfo=BEIJING)


def test_next_beijing_midnight_is_timezone_aware() -> None:
    now = datetime(2026, 11, 13, 23, 59, tzinfo=UTC)

    target = next_beijing_midnight(now)

    assert target.tzinfo is not None
    assert target == datetime(2026, 11, 15, 0, 0, 0, tzinfo=BEIJING)


def test_scheduler_thread_stops_without_running_before_midnight() -> None:
    stop = Event()
    thread = start_equity_snapshot_scheduler(stop)
    stop.set()
    thread.join(timeout=2.0)

    assert not thread.is_alive()

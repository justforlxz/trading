"""每日权益快照：北京时间 00:00 在同一进程内触发一次 OKX 只读同步。

单进程部署没有独立调度器，任务用一条守护线程等待下一个北京时间零点；等待本身
可被停止事件立即打断，因此应用退出时不会留下悬挂线程。

调度只决定「什么时候跑」，采集与落库仍由 `app.positions.sync_account` 完成。
未配置凭据时该函数返回 `unconfigured`，任务不会伪造一条空快照。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from threading import Event, Thread
from zoneinfo import ZoneInfo

from app.core import Clock, SystemClock
from app.positions import AccountSyncView, sync_account

__all__ = [
    "next_beijing_midnight",
    "run_daily_equity_snapshot",
    "start_equity_snapshot_scheduler",
]

logger = logging.getLogger(__name__)

BEIJING = ZoneInfo("Asia/Shanghai")
#: 停止等待时最多再给线程几秒完成一次正在执行的同步。
STOP_TIMEOUT_SECONDS = 5.0


def next_beijing_midnight(now: datetime) -> datetime:
    """`now` 之后最近的一个北京时间 00:00（带时区）。"""

    if now.tzinfo is None:
        raise ValueError("now 必须带时区")
    local = now.astimezone(BEIJING)
    candidate = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate


def run_daily_equity_snapshot(*, clock: Clock | None = None) -> AccountSyncView:
    """执行一次权益快照；异常由调用方处理，任务本身不吞掉同步失败的证据。"""

    return sync_account(clock=clock)


def start_equity_snapshot_scheduler(
    stop: Event,
    *,
    clock: Clock | None = None,
) -> Thread:
    """启动等待北京时间零点的守护线程；`stop.set()` 会立即结束等待。"""

    scheduler_clock = clock or SystemClock()

    def _loop() -> None:
        while not stop.is_set():
            now = scheduler_clock.now()
            target = next_beijing_midnight(now)
            if stop.wait(max((target - now).total_seconds(), 0.0)):
                return
            if stop.is_set():
                return
            try:
                result = run_daily_equity_snapshot(clock=scheduler_clock)
            except Exception:
                logger.exception("每日权益快照失败")
                continue
            logger.info(
                "每日权益快照完成: status=%s captured_at=%s",
                result.summary.status,
                result.summary.captured_at,
            )

    thread = Thread(target=_loop, name="trading-equity-snapshot", daemon=True)
    thread.start()
    return thread

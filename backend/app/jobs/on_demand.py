"""按需 K 线同步：进程内后台队列，按「标的 + 周期」去重。

用户明确打开某个标的或把它加入自选时才同步对应周期。单进程部署没有独立 worker，
队列就是本进程里的固定数量守护线程：并发上限由配置决定，提交只入队不等待上游，
同步失败由 `run_candle_sync` 自己写 `data_sync_jobs`，调度器只记录冷却状态。

去重键是 `(inst_id, bar)`：正在跑时返回 `already_running`；最近一次成功在 60 秒内
返回 `fresh`；最近一次失败在 30 秒内返回 `backoff`。这样连续刷新页面不会把上游
打成限流。

进程退出时 `shutdown()` 丢弃尚未开始的任务，并最多等待正在执行的任务一段时间；
线程是守护线程，超时后进程可以直接退出，不会留下阻塞退出的无限线程。
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import Condition, Thread
from time import monotonic
from typing import Literal

from app.jobs.sync import run_candle_sync

__all__ = [
    "BACKOFF_SECONDS",
    "DEFAULT_DAYS_BY_BAR",
    "DEFAULT_MAX_CONCURRENCY",
    "FRESH_SECONDS",
    "SHUTDOWN_TIMEOUT_SECONDS",
    "WATCHLIST_BAR",
    "WATCHLIST_DAYS",
    "OnDemandSyncScheduler",
    "SyncStatus",
    "SyncSubmission",
]

logger = logging.getLogger(__name__)

SyncStatus = Literal["started", "already_running", "fresh", "backoff"]

#: 整个调度器最多同时跑两个同步任务，避免连续打开多个页面时打满上游。
DEFAULT_MAX_CONCURRENCY = 2
#: 最近一次成功之后的冷却时间；这段时间内重复请求不再打上游。
FRESH_SECONDS = 60.0
#: 最近一次失败之后的冷却时间；避免页面反复打开时连续重试。
BACKOFF_SECONDS = 30.0
#: 退出时等待正在执行任务的上限；超时后守护线程随进程退出。
SHUTDOWN_TIMEOUT_SECONDS = 5.0

#: 各周期的默认回看窗口（天）。
DEFAULT_DAYS_BY_BAR: dict[str, int] = {"1d": 400, "4h": 90, "1h": 30}
WATCHLIST_BAR = "1d"
WATCHLIST_DAYS = DEFAULT_DAYS_BY_BAR[WATCHLIST_BAR]

SyncCall = Callable[[str, str, int], object]


def _run_candle_sync(inst_id: str, bar: str, days: int) -> object:
    """默认执行：复用现有单标的 K 线同步，不在这里另写取数逻辑。"""

    return run_candle_sync([inst_id], bar=bar, days=days)


@dataclass(frozen=True, slots=True)
class SyncSubmission:
    """一次提交的去重结果；`status` 直接作为接口响应取值。"""

    status: SyncStatus


class OnDemandSyncScheduler:
    """固定并发上限的进程内队列；同一个 `(inst_id, bar)` 同时只有一个任务。"""

    def __init__(
        self,
        *,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        fresh_seconds: float = FRESH_SECONDS,
        backoff_seconds: float = BACKOFF_SECONDS,
        sync: SyncCall | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency 必须大于 0")
        self._max_concurrency = max_concurrency
        self._fresh_seconds = fresh_seconds
        self._backoff_seconds = backoff_seconds
        self._sync = sync or _run_candle_sync
        self._clock = clock or monotonic
        self._condition = Condition()
        self._pending: deque[tuple[tuple[str, str], int]] = deque()
        self._running: set[tuple[str, str]] = set()
        self._last_success: dict[tuple[str, str], float] = {}
        self._last_failure: dict[tuple[str, str], float] = {}
        self._workers: list[Thread] = []
        self._stopped = False

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

    def submit(self, inst_id: str, bar: str, days: int) -> SyncSubmission:
        """入队一次同步；相同键在运行中、刚成功或刚失败时直接返回对应状态。"""

        key = (inst_id, bar)
        now = self._clock()
        with self._condition:
            if self._stopped:
                raise RuntimeError("按需同步调度器已停止")
            if key in self._running:
                return SyncSubmission("already_running")
            succeeded_at = self._last_success.get(key)
            if succeeded_at is not None and now - succeeded_at < self._fresh_seconds:
                return SyncSubmission("fresh")
            failed_at = self._last_failure.get(key)
            if failed_at is not None and now - failed_at < self._backoff_seconds:
                return SyncSubmission("backoff")
            self._running.add(key)
            self._pending.append((key, days))
            self._ensure_workers()
            self._condition.notify_all()
        return SyncSubmission("started")

    def shutdown(self, *, timeout: float = SHUTDOWN_TIMEOUT_SECONDS) -> None:
        """停止接收新任务，丢弃排队任务，并有限等待正在执行的任务。"""

        with self._condition:
            if self._stopped:
                return
            self._stopped = True
            self._pending.clear()
            self._condition.notify_all()
        deadline = monotonic() + max(timeout, 0.0)
        for worker in list(self._workers):
            worker.join(max(deadline - monotonic(), 0.0))
        still_running = [worker.name for worker in self._workers if worker.is_alive()]
        if still_running:
            logger.warning("按需同步任务在退出等待后仍在执行: %s", ", ".join(still_running))

    def _ensure_workers(self) -> None:
        """首个任务到达时把固定数量的守护线程建好，数量不超过并发上限。"""

        while len(self._workers) < self._max_concurrency:
            worker = Thread(
                target=self._work,
                name=f"trading-on-demand-sync-{len(self._workers) + 1}",
                daemon=True,
            )
            worker.start()
            self._workers.append(worker)

    def _work(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._stopped:
                    self._condition.wait()
                if not self._pending:
                    return
                key, days = self._pending.popleft()
            inst_id, bar = key
            try:
                self._sync(inst_id, bar, days)
            except Exception:
                # `run_candle_sync` 已经把失败写进 `data_sync_jobs`；这里只记录冷却状态，
                # 不让异常冒到线程栈之外，也不把同步失败变成用户请求的错误。
                logger.exception("按需同步失败: inst_id=%s bar=%s", inst_id, bar)
                with self._condition:
                    self._last_failure[key] = self._clock()
            else:
                with self._condition:
                    self._last_success[key] = self._clock()
                    self._last_failure.pop(key, None)
            finally:
                with self._condition:
                    self._running.discard(key)
                    self._condition.notify_all()

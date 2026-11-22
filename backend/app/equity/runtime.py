"""进程内的美股同步状态：最近一次 tick、下次计划、退避与最近结果。

只保存「刚刚发生过什么」，不保存 K 线本身——K 线在 `candles` 表里，进程重启后仍然在。
重启后这里清空，健康组件如实显示「尚未运行」，不编造上次成功时间。

美股只有一个抓取单元（一次 tick 抓全部标的），因此这里不需要宏观那种「按序列 + 粒度
分桶」的结构：一个失败计数、一把非阻塞锁就够了。
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any

__all__ = ["DEGRADE_AFTER_FAILURES", "MAX_BACKOFF_EXPONENT", "EquityRuntime"]

#: 连续失败到这个次数就标记 degraded，健康组件降为 error。
DEGRADE_AFTER_FAILURES = 3
#: 退避倍数的上限指数：1× / 2× / 4×，不无限翻倍。
MAX_BACKOFF_EXPONENT = 2


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


class EquityRuntime:
    """美股抓取的进程内状态；所有读写都在同一把锁下，调度器与健康组件共用。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self.failures = 0
        self.degraded = False
        self.last_error: str | None = None
        self.last_error_at: datetime | None = None
        self.last_success_at: datetime | None = None
        self.retry_at: datetime | None = None
        self.last_run_at: datetime | None = None
        self.next_run_at: datetime | None = None
        self.duration_ms: int | None = None

    def reset(self) -> None:
        """清空全部状态；测试在用例之间调用，生产只在进程启动时为空。"""

        with self._lock:
            self._running = False
            self.failures = 0
            self.degraded = False
            self.last_error = None
            self.last_error_at = None
            self.last_success_at = None
            self.retry_at = None
            self.last_run_at = None
            self.next_run_at = None
            self.duration_ms = None

    def acquire(self) -> bool:
        """尝试占用抓取；已有一次在跑时立即返回 `False`，不排队（同源并发保护）。"""

        with self._lock:
            if self._running:
                return False
            self._running = True
            return True

    def release(self) -> None:
        with self._lock:
            self._running = False

    def record_success(self, now: datetime) -> None:
        with self._lock:
            self.failures = 0
            self.degraded = False
            self.last_error = None
            self.last_error_at = None
            self.retry_at = None
            self.last_success_at = now

    def record_failure(self, now: datetime, *, interval_seconds: int, message: str) -> None:
        with self._lock:
            self.failures += 1
            self.last_error = message
            self.last_error_at = now
            exponent = min(self.failures - 1, MAX_BACKOFF_EXPONENT)
            self.retry_at = now + timedelta(seconds=interval_seconds * (2**exponent))
            if self.failures >= DEGRADE_AFTER_FAILURES:
                self.degraded = True

    def in_backoff(self, now: datetime) -> bool:
        """是否还在退避窗口内；窗口结束就放行一次试探抓取。

        `degraded` 只用于健康组件展示，**不参与**这里的判定：把它当成「永远在退避」
        会让连续失败的单元再也抓不到，而清空 `degraded` 的成功路径又要先抓到才有——
        两条路径互为前提，单元会永久停摆。
        """

        with self._lock:
            return self.retry_at is not None and now < self.retry_at

    def plan_next(self, next_run_at: datetime) -> None:
        """登记下次计划运行时刻；启动时先登记，健康组件在首次 tick 之前也有「下次」。"""

        with self._lock:
            self.next_run_at = next_run_at

    def record_tick(self, *, now: datetime, next_run_at: datetime, duration_ms: int) -> None:
        with self._lock:
            self.last_run_at = now
            self.next_run_at = next_run_at
            self.duration_ms = duration_ms

    def staleness(self) -> tuple[bool, str | None]:
        """当前是否处于抓取失败状态；有就返回那条错误，供总览标记「缓存值 + stale」。

        失败事实必须能被首页读到：库里还有上一次成功的 K 线时，HTTP 仍返回 200 与那些
        值，但它们已经不是「当前可用数据」——健康组件看得见失败，首页也必须看得见。
        下一次成功会清空 `last_error`，标记随之消失。
        """

        with self._lock:
            if self.last_error:
                return True, self.last_error
            return False, None

    def status(self) -> dict[str, Any]:
        """给健康组件看的快照：最近运行、下次计划、耗时与最近一次错误。"""

        with self._lock:
            return {
                "last_run_at": _iso(self.last_run_at),
                "next_run_at": _iso(self.next_run_at),
                "duration_ms": self.duration_ms,
                "last_success_at": _iso(self.last_success_at),
                "last_error": self.last_error,
                "failures": self.failures,
                "degraded": self.degraded,
            }

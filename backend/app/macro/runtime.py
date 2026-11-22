"""进程内的宏观同步状态：每单元锁、连续失败次数、退避与最近结果。

只保存「刚刚发生过什么」，不保存观测值本身——观测值在库里，进程重启后仍然在。
重启后这里清空，健康组件如实显示「尚未运行」，不编造上次成功时间。

单元键是「序列 + 粒度」：同一序列的分钟级与日线级是两个独立的抓取任务，其中一个
失败不能让另一个也进退避。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.macro.config import SeriesUnit

__all__ = ["DEGRADE_AFTER_FAILURES", "MAX_BACKOFF_EXPONENT", "MacroRuntime", "UnitState"]

#: 连续失败到这个次数就标记 degraded，健康组件降为 error。
DEGRADE_AFTER_FAILURES = 3
#: 退避倍数的上限指数：1× / 2× / 4×，不无限翻倍。
MAX_BACKOFF_EXPONENT = 2


@dataclass(slots=True)
class UnitState:
    """一个抓取单元的运行时状态。"""

    failures: int = 0
    degraded: bool = False
    last_error: str | None = None
    last_error_at: datetime | None = None
    last_success_at: datetime | None = None
    retry_at: datetime | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


class MacroRuntime:
    """宏观抓取的进程内状态；所有读写都在同一把锁下，调度器与手动同步共用。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._units: dict[tuple[str, str], UnitState] = {}
        self.last_run_at: datetime | None = None
        self.next_run_at: datetime | None = None
        self.duration_ms: int | None = None

    def reset(self) -> None:
        """清空全部状态；测试在用例之间调用，生产只在进程启动时为空。"""

        with self._lock:
            self._units.clear()
            self.last_run_at = None
            self.next_run_at = None
            self.duration_ms = None

    def acquire(self, unit: SeriesUnit) -> bool:
        """尝试占用单元；已被别的调用占用时立即返回 `False`，不排队。"""

        return self._state(unit).lock.acquire(blocking=False)

    def release(self, unit: SeriesUnit) -> None:
        self._state(unit).lock.release()

    def record_success(self, unit: SeriesUnit, now: datetime) -> None:
        with self._lock:
            state = self._state_locked(unit)
            state.failures = 0
            state.degraded = False
            state.last_error = None
            state.last_error_at = None
            state.retry_at = None
            state.last_success_at = now

    def record_failure(
        self,
        unit: SeriesUnit,
        now: datetime,
        *,
        interval_seconds: int,
        message: str,
    ) -> None:
        with self._lock:
            state = self._state_locked(unit)
            state.failures += 1
            state.last_error = message
            state.last_error_at = now
            exponent = min(state.failures - 1, MAX_BACKOFF_EXPONENT)
            state.retry_at = now + timedelta(seconds=interval_seconds * (2**exponent))
            if state.failures >= DEGRADE_AFTER_FAILURES:
                state.degraded = True

    def in_backoff(self, unit: SeriesUnit, now: datetime) -> bool:
        """是否还在退避窗口内；窗口结束就放行一次试探抓取。

        `degraded` 只用于健康组件展示，**不参与**这里的判定：把它当成「永远在退避」会让
        连续失败的单元再也抓不到，而清空 `degraded` 的成功路径又要先抓到才有——两条
        路径互为前提，单元会永久停摆。
        """

        with self._lock:
            state = self._state_locked(unit)
            return state.retry_at is not None and now < state.retry_at

    def plan_next(self, next_run_at: datetime) -> None:
        """登记下次计划运行时刻；启动时先登记，健康组件在首次 tick 之前也有「下次」。"""

        with self._lock:
            self.next_run_at = next_run_at

    def record_tick(
        self,
        *,
        now: datetime,
        next_run_at: datetime,
        duration_ms: int,
    ) -> None:
        with self._lock:
            self.last_run_at = now
            self.next_run_at = next_run_at
            self.duration_ms = duration_ms

    def staleness(self) -> tuple[bool, str | None]:
        """当前是否有单元处于失败状态；有就返回第一条错误作为降级原因。"""

        with self._lock:
            errors = [state.last_error for state in self._units.values() if state.last_error]
        return (True, errors[0]) if errors else (False, None)

    def status(self) -> dict[str, Any]:
        """给健康组件看的快照：整体时间与逐单元状态，全部是 JSON 可序列化值。"""

        with self._lock:
            series = [
                {
                    "series_id": key[0],
                    "granularity": key[1],
                    "failures": state.failures,
                    "degraded": state.degraded,
                    "last_success_at": _iso(state.last_success_at),
                    "last_error": state.last_error,
                }
                for key, state in sorted(self._units.items())
            ]
            successes = [
                state.last_success_at
                for state in self._units.values()
                if state.last_success_at is not None
            ]
            errors = [state.last_error for state in self._units.values() if state.last_error]
            degraded = any(state.degraded for state in self._units.values())
            return {
                "last_run_at": _iso(self.last_run_at),
                "next_run_at": _iso(self.next_run_at),
                "duration_ms": self.duration_ms,
                "last_success_at": _iso(max(successes)) if successes else None,
                "last_error": errors[0] if errors else None,
                "degraded": degraded,
                "series": series,
            }

    def _state(self, unit: SeriesUnit) -> UnitState:
        with self._lock:
            return self._state_locked(unit)

    def _state_locked(self, unit: SeriesUnit) -> UnitState:
        """调用方必须已持有 `self._lock`，或接受 `setdefault` 的原子性。"""

        key = (unit.series_id, unit.granularity)
        state = self._units.get(key)
        if state is None:
            state = UnitState()
            self._units[key] = state
        return state

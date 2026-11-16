"""按需同步调度器：去重键、成功/失败冷却、并发上限与退出策略。

断言只看调度器自己返回的状态和真实执行过的调用列表，不用耗时推断并发。
"""

from __future__ import annotations

import threading
import time

from app.jobs import OnDemandSyncScheduler

WAIT_SECONDS = 2.0


def _wait_for_status(
    scheduler: OnDemandSyncScheduler,
    inst_id: str,
    bar: str,
    expected: str,
    *,
    timeout: float = WAIT_SECONDS,
) -> str:
    """轮询到期望状态；轮询本身不会新增任务，因为返回都是已有状态之一。"""

    deadline = time.monotonic() + timeout
    status = "already_running"
    while time.monotonic() < deadline:
        status = scheduler.submit(inst_id, bar, 400).status
        if status == expected:
            return status
        time.sleep(0.01)
    raise AssertionError(f"等待状态 {expected} 超时, 实际 {status}")


def test_same_key_is_deduplicated_to_one_task() -> None:
    started = threading.Event()
    release = threading.Event()
    calls: list[tuple[str, str, int]] = []

    def sync(inst_id: str, bar: str, days: int) -> None:
        calls.append((inst_id, bar, days))
        started.set()
        release.wait(5)

    scheduler = OnDemandSyncScheduler(sync=sync)
    try:
        statuses = [scheduler.submit("XAAPL-USDT", "1d", 400).status for _ in range(10)]
        assert statuses.count("started") == 1
        assert statuses.count("already_running") == 9
        assert started.wait(2)
        assert calls == [("XAAPL-USDT", "1d", 400)]
    finally:
        release.set()
        scheduler.shutdown()


def test_success_cooldown_returns_fresh_then_allows_retry() -> None:
    clock = [1000.0]
    calls = 0
    finished = threading.Event()

    def sync(inst_id: str, bar: str, days: int) -> None:
        nonlocal calls
        calls += 1
        finished.set()

    scheduler = OnDemandSyncScheduler(sync=sync, clock=lambda: clock[0])
    try:
        assert scheduler.submit("XAAPL-USDT", "1d", 400).status == "started"
        assert finished.wait(2)
        assert _wait_for_status(scheduler, "XAAPL-USDT", "1d", "fresh") == "fresh"
        assert calls == 1

        clock[0] += 61
        assert scheduler.submit("XAAPL-USDT", "1d", 400).status == "started"
    finally:
        scheduler.shutdown()


def test_failure_cooldown_returns_backoff_and_keeps_exception_out_of_submit() -> None:
    clock = [1000.0]
    calls = 0
    finished = threading.Event()

    def sync(inst_id: str, bar: str, days: int) -> None:
        nonlocal calls
        calls += 1
        finished.set()
        if calls == 1:
            raise RuntimeError("上游 429")

    scheduler = OnDemandSyncScheduler(sync=sync, clock=lambda: clock[0])
    try:
        assert scheduler.submit("XAAPL-USDT", "1d", 400).status == "started"
        assert finished.wait(2)
        assert _wait_for_status(scheduler, "XAAPL-USDT", "1d", "backoff") == "backoff"
        assert calls == 1

        clock[0] += 31
        assert scheduler.submit("XAAPL-USDT", "1d", 400).status == "started"
    finally:
        scheduler.shutdown()


def test_different_bars_are_independent() -> None:
    clock = [1000.0]
    calls: list[tuple[str, str]] = []
    done = threading.Event()

    def sync(inst_id: str, bar: str, days: int) -> None:
        calls.append((inst_id, bar))
        if len(calls) == 2:
            done.set()

    scheduler = OnDemandSyncScheduler(sync=sync, clock=lambda: clock[0], max_concurrency=2)
    try:
        assert scheduler.submit("XAAPL-USDT", "1d", 400).status == "started"
        assert scheduler.submit("XAAPL-USDT", "4h", 90).status == "started"
        assert done.wait(2)
        assert sorted(calls) == [("XAAPL-USDT", "1d"), ("XAAPL-USDT", "4h")]
        assert _wait_for_status(scheduler, "XAAPL-USDT", "1d", "fresh") == "fresh"
        assert _wait_for_status(scheduler, "XAAPL-USDT", "4h", "fresh") == "fresh"
    finally:
        scheduler.shutdown()


def test_concurrency_never_exceeds_the_cap() -> None:
    barrier = threading.Barrier(2, timeout=5)
    lock = threading.Lock()
    active = 0
    peak = 0
    completed = threading.Event()
    remaining = 4

    def sync(inst_id: str, bar: str, days: int) -> None:
        nonlocal active, peak, remaining
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            barrier.wait()
        finally:
            with lock:
                active -= 1
                remaining -= 1
                if remaining == 0:
                    completed.set()

    scheduler = OnDemandSyncScheduler(sync=sync, max_concurrency=2)
    try:
        for inst_id in ("A-USDT", "B-USDT", "C-USDT", "D-USDT"):
            assert scheduler.submit(inst_id, "1d", 400).status == "started"
        assert completed.wait(5)
        assert peak == 2
    finally:
        scheduler.shutdown()


def test_shutdown_drops_queued_tasks_and_stops_workers() -> None:
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def sync(inst_id: str, bar: str, days: int) -> None:
        calls.append(inst_id)
        started.set()
        release.wait(5)

    scheduler = OnDemandSyncScheduler(sync=sync, max_concurrency=1)
    try:
        assert scheduler.submit("A-USDT", "1d", 400).status == "started"
        assert scheduler.submit("B-USDT", "1d", 400).status == "started"
        assert started.wait(2)
        scheduler.shutdown(timeout=0.05)
        release.set()
        time.sleep(0.1)
        assert calls == ["A-USDT"]
    finally:
        release.set()
        scheduler.shutdown()

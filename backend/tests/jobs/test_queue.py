"""进程内队列：并发上限、峰值由队列自身上报、单个任务失败不拖垮整批。

峰值断言不用「耗时推断」也不用日志：任务里放一道 `threading.Barrier(2)`，只有两个任务
真的同时在跑时这道栅栏才会放行。若队列实际是串行的，栅栏等到超时就抛
`BrokenBarrierError`，该任务的结果变成错误，峰值也就到不了 2——两种情况都会让用例红。
"""

from __future__ import annotations

import threading

import pytest

from app.core import ValidationError
from app.jobs import DEFAULT_MAX_CONCURRENCY, QueueOutcome, QueueReport, run_tasks

BARRIER_TIMEOUT = 10


def test_run_tasks_reports_a_peak_equal_to_the_cap() -> None:
    """6 个任务、上限 2：两两在栅栏处会合，峰值必然到 2 且不超过 2。"""

    barrier = threading.Barrier(DEFAULT_MAX_CONCURRENCY, timeout=BARRIER_TIMEOUT)

    def rendezvous(index: int) -> int:
        barrier.wait()
        return index

    report: QueueReport[int] = run_tasks(
        [lambda index=index: rendezvous(index) for index in range(6)]
    )

    assert report.peak_running == 2
    assert report.max_concurrency == 2
    assert [outcome.value for outcome in report.outcomes] == [0, 1, 2, 3, 4, 5]
    assert [outcome.error for outcome in report.outcomes] == [None] * 6


def test_run_tasks_serialises_when_the_cap_is_one() -> None:
    report = run_tasks([lambda index=index: index for index in range(4)], max_concurrency=1)

    assert report.peak_running == 1
    assert report.max_concurrency == 1
    assert [outcome.value for outcome in report.outcomes] == [0, 1, 2, 3]


def test_run_tasks_honours_an_explicit_cap_below_the_batch_size() -> None:
    barrier = threading.Barrier(3, timeout=BARRIER_TIMEOUT)

    def rendezvous(index: int) -> int:
        barrier.wait()
        return index

    report = run_tasks(
        [lambda index=index: rendezvous(index) for index in range(9)],
        max_concurrency=3,
    )

    assert report.peak_running == 3
    assert len(report.outcomes) == 9


def test_run_tasks_keeps_going_after_a_task_fails() -> None:
    def boom() -> int:
        raise RuntimeError("行情缺失")

    report: QueueReport[int] = run_tasks([lambda: 1, boom, lambda: 3], max_concurrency=1)
    failed: QueueOutcome[int] = report.outcomes[1]

    assert report.outcomes[0].value == 1
    assert failed.value is None
    assert failed.error == "RuntimeError: 行情缺失"
    assert report.outcomes[2].value == 3


def test_run_tasks_returns_an_empty_report_for_an_empty_batch() -> None:
    report = run_tasks([])

    assert report.outcomes == ()
    assert report.peak_running == 0
    assert report.max_concurrency == DEFAULT_MAX_CONCURRENCY


@pytest.mark.parametrize("limit", [0, -1, 1.5, True])
def test_run_tasks_rejects_a_bad_concurrency_limit(limit: object) -> None:
    with pytest.raises(ValidationError, match="并发上限"):
        run_tasks([], max_concurrency=limit)  # type: ignore[arg-type]


def test_run_tasks_rejects_a_non_callable_task() -> None:
    with pytest.raises(ValidationError, match="不是可调用对象"):
        run_tasks([lambda: 1, 2])  # type: ignore[list-item]

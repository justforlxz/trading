"""进程内队列：单进程部署下的并发上限与并发峰值上报。

没有 Redis、没有独立 worker：整个队列就是一池线程加一把计数锁。批量的每一格回测都是
同步 CPU 计算，放进线程池即可——单进程部署下真正的瓶颈是「同时跑几格」，不是线程模型。

## 峰值由队列自己记

`QueueReport.peak_running` 是队列在任务进出时自己数的「同时处于 running 的最大值」，
不是从日志或耗时推断出来的。调用方要断言「并发不超过 N」，读这个数就够。

## 一个失败不拖垮整批

任务抛出的异常被折成该任务的 `QueueOutcome.error`（带异常类型名与消息），同批其余任务
照常跑完、照常返回。批量回测里一条腿缺数据不该让另外几十格结果消失；失败原因跟着它
自己那一格回去，由调用方原样展示。

## 上限

`max_concurrency` 是整批的上限，不是每个任务的上限；它同时决定线程池大小，因此
`peak_running` 恒不超过它。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock

from app.core import ValidationError

__all__ = ["DEFAULT_MAX_CONCURRENCY", "QueueOutcome", "QueueReport", "run_tasks"]

#: 批量回测默认同时跑两格：个人工作台上再多只会互相抢 CPU，把单格耗时拉长。
DEFAULT_MAX_CONCURRENCY = 2


@dataclass(frozen=True, slots=True)
class QueueOutcome[TaskResult]:
    """一个任务的执行结果：成功带值，失败带可读错误，二者恰有其一。"""

    value: TaskResult | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class QueueReport[TaskResult]:
    """整批的结果：按任务提交顺序排列，附队列自身上报的并发峰值。"""

    outcomes: tuple[QueueOutcome[TaskResult], ...]
    peak_running: int
    max_concurrency: int


class _RunningCounter:
    """同时处于 running 的任务数，以及它达到过的最大值。

    只在这把锁里读写：进出各自一次加/减，峰值在进入时更新，因此峰值是「真的同时」，
    不是「先后加起来」。
    """

    __slots__ = ("_lock", "_peak", "_running")

    def __init__(self) -> None:
        self._lock = Lock()
        self._running = 0
        self._peak = 0

    def enter(self) -> None:
        with self._lock:
            self._running += 1
            self._peak = max(self._peak, self._running)

    def leave(self) -> None:
        with self._lock:
            self._running -= 1

    @property
    def peak(self) -> int:
        with self._lock:
            return self._peak


def run_tasks[TaskResult](
    tasks: Sequence[Callable[[], TaskResult]],
    *,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
) -> QueueReport[TaskResult]:
    """按提交顺序跑完一批无参任务，返回逐任务结果与队列自身上报的并发峰值。

    空批次返回空结果与峰值 0（不是「一个失败」）；并发上限不是正整数、或某个任务不是
    可调用对象时判错——这类问题若被吞掉，整批会安静地少跑几格。
    """

    if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int):
        raise ValidationError(f"并发上限必须是整数, 实际 {max_concurrency!r}")
    if max_concurrency < 1:
        raise ValidationError(f"并发上限必须 ≥1, 实际 {max_concurrency}")

    batch = tuple(tasks)
    for index, task in enumerate(batch):
        if not callable(task):
            raise ValidationError(f"第 {index} 个任务不是可调用对象")

    if not batch:
        return QueueReport(outcomes=(), peak_running=0, max_concurrency=max_concurrency)

    counter = _RunningCounter()
    with ThreadPoolExecutor(
        max_workers=max_concurrency, thread_name_prefix="trading-queue"
    ) as pool:
        # 先把整批提交出去再收结果：边提交边 result() 会把并发压回 1。
        futures = [pool.submit(_capture, counter, task) for task in batch]
        outcomes = tuple(future.result() for future in futures)
    return QueueReport(
        outcomes=outcomes,
        peak_running=counter.peak,
        max_concurrency=max_concurrency,
    )


def _capture[TaskResult](
    counter: _RunningCounter,
    task: Callable[[], TaskResult],
) -> QueueOutcome[TaskResult]:
    """跑一个任务并把异常折成可读错误；进出计数保证峰值真实。"""

    counter.enter()
    try:
        return QueueOutcome(value=task())
    except Exception as exc:
        return QueueOutcome(error=f"{type(exc).__name__}: {exc}")
    finally:
        counter.leave()

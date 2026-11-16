"""按需同步调度器的测试替身：记录提交，不启动任何后台线程或上游请求。"""

from __future__ import annotations

from app.jobs import SyncSubmission

__all__ = ["RecordingScheduler", "RejectingScheduler"]


class RecordingScheduler:
    """记录每次提交的参数；状态固定为 `started`。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self.shutdown_calls = 0

    def submit(self, inst_id: str, bar: str, days: int) -> SyncSubmission:
        self.calls.append((inst_id, bar, days))
        return SyncSubmission("started")

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class RejectingScheduler:
    """提交即抛错，用于证明加入自选不会因为调度失败而回滚。"""

    def submit(self, inst_id: str, bar: str, days: int) -> SyncSubmission:
        raise RuntimeError(f"拒绝同步 {inst_id} {bar} {days}")

    def shutdown(self) -> None:
        return None

"""周期全市场扫描（P1-11 AC11）：间隔来自配置，到期只投递一次。"""

from app.config import Settings
from app.jobs import tasks
from app.jobs.schedule import PeriodicTask, build_schedule
from app.jobs.scheduler import tick


class FakeRedis:
    """最小 `SET NX EX` 语义：已存在的键不会被再次「获取租约」。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: object, *, ex: int | None = None, nx: bool = False):
        if nx and key in self.store:
            return None
        self.store[key] = str(value)
        return True

    async def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0


def test_scan_interval_comes_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("OPPORTUNITY_SCAN_INTERVAL_SECONDS", "120")

    schedule = build_schedule(Settings())

    entry = next(item for item in schedule if item.task_name == tasks.SCAN_OPPORTUNITIES)
    assert entry.name == tasks.SCAN_OPPORTUNITIES
    assert entry.interval_seconds == 120


def test_scan_interval_default_is_one_hour() -> None:
    entry = next(
        item for item in build_schedule(Settings()) if item.task_name == tasks.SCAN_OPPORTUNITIES
    )
    assert entry.interval_seconds == 3600


async def test_due_scan_dispatches_once_and_is_skipped_before_next_interval() -> None:
    task = PeriodicTask(tasks.SCAN_OPPORTUNITIES, tasks.SCAN_OPPORTUNITIES, 60)
    redis = FakeRedis()
    dispatched: list[tuple[str, int | None]] = []

    async def start_run(task_name: str) -> int:
        assert task_name == tasks.SCAN_OPPORTUNITIES
        return 7

    async def enqueue(task_name: str, run_id: int | None) -> None:
        dispatched.append((task_name, run_id))

    async def fail_run(run_id: int, error: str) -> None:  # pragma: no cover - 不应被调用
        raise AssertionError(f"unexpected failure: {run_id} {error}")

    for _ in range(3):
        await tick(
            redis,
            5.0,
            schedule=[task],
            enqueue=enqueue,
            start_run=start_run,
            fail_run=fail_run,
        )

    assert dispatched == [(tasks.SCAN_OPPORTUNITIES, 7)]

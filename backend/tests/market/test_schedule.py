"""调度器：租约、任务账本与 run_id 传递。"""

from app.jobs.schedule import SCHEDULE_KEY_PREFIX, PeriodicTask
from app.jobs.scheduler import HEARTBEAT_KEY, tick

TASK = PeriodicTask("sync_instruments", "sync_instruments", 3600)


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: object, *, ex: int | None = None, nx: bool = False):
        if nx and key in self.store:
            return None
        self.store[key] = str(value)
        return True

    async def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0


class Recorder:
    def __init__(self) -> None:
        self.dispatched: list[tuple[str, int | None]] = []
        self.failed: list[tuple[int, str]] = []
        self.next_run_id = 41

    async def start_run(self, task_name: str) -> int:
        return self.next_run_id

    async def enqueue(self, task_name: str, run_id: int | None) -> None:
        self.dispatched.append((task_name, run_id))

    async def fail_run(self, run_id: int, error: str) -> None:
        self.failed.append((run_id, error))


async def test_tick_creates_run_and_enqueues_once() -> None:
    redis = FakeRedis()
    recorder = Recorder()

    await tick(
        redis,
        5.0,
        schedule=[TASK],
        enqueue=recorder.enqueue,
        start_run=recorder.start_run,
        fail_run=recorder.fail_run,
    )
    await tick(
        redis,
        5.0,
        schedule=[TASK],
        enqueue=recorder.enqueue,
        start_run=recorder.start_run,
        fail_run=recorder.fail_run,
    )

    assert HEARTBEAT_KEY in redis.store
    assert recorder.dispatched == [("sync_instruments", 41)]
    assert f"{SCHEDULE_KEY_PREFIX}sync_instruments" in redis.store


async def test_failed_enqueue_releases_lease_and_fails_run() -> None:
    redis = FakeRedis()
    recorder = Recorder()
    attempts: list[str] = []

    async def enqueue(task_name: str, run_id: int | None) -> None:
        attempts.append(task_name)
        if len(attempts) == 1:
            raise RuntimeError("redis down")

    await tick(
        redis,
        5.0,
        schedule=[TASK],
        enqueue=enqueue,
        start_run=recorder.start_run,
        fail_run=recorder.fail_run,
    )
    await tick(
        redis,
        5.0,
        schedule=[TASK],
        enqueue=enqueue,
        start_run=recorder.start_run,
        fail_run=recorder.fail_run,
    )

    assert attempts == ["sync_instruments", "sync_instruments"]
    assert recorder.failed == [(41, "redis down")]
    assert f"{SCHEDULE_KEY_PREFIX}sync_instruments" in redis.store


def test_every_scheduled_task_is_registered_on_the_worker() -> None:
    """调度表投递的函数名必须与 worker 注册名一致（否则任务永远 not found）。"""

    from app.jobs.schedule import build_schedule
    from app.jobs.tasks import TASK_FUNCTIONS

    registered = {function.__name__ for function in TASK_FUNCTIONS}
    for task in build_schedule():
        assert task.task_name in registered, task.task_name

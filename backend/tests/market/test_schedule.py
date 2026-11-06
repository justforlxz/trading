"""调度器租约（jobs）：同一任务在间隔内只投递一次，失败释放租约。"""

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


async def test_tick_writes_heartbeat_and_enqueues_once() -> None:
    redis = FakeRedis()
    enqueued: list[str] = []

    async def enqueue(task_name: str) -> None:
        enqueued.append(task_name)

    await tick(redis, 5.0, schedule=[TASK], enqueue=enqueue)
    await tick(redis, 5.0, schedule=[TASK], enqueue=enqueue)

    assert HEARTBEAT_KEY in redis.store
    assert enqueued == ["sync_instruments"]
    assert f"{SCHEDULE_KEY_PREFIX}sync_instruments" in redis.store


async def test_failed_enqueue_releases_lease() -> None:
    redis = FakeRedis()
    attempts: list[str] = []

    async def enqueue(task_name: str) -> None:
        attempts.append(task_name)
        if len(attempts) == 1:
            raise RuntimeError("redis down")

    await tick(redis, 5.0, schedule=[TASK], enqueue=enqueue)
    await tick(redis, 5.0, schedule=[TASK], enqueue=enqueue)

    assert attempts == ["sync_instruments", "sync_instruments"]
    assert f"{SCHEDULE_KEY_PREFIX}sync_instruments" in redis.store


def test_every_scheduled_task_is_registered_on_the_worker() -> None:
    """调度表投递的函数名必须与 worker 注册名一致（否则任务永远 not found）。"""

    from app.jobs.schedule import build_schedule
    from app.jobs.tasks import TASK_FUNCTIONS

    registered = {function.__name__ for function in TASK_FUNCTIONS}
    for task in build_schedule():
        assert task.task_name in registered, task.task_name

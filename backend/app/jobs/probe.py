"""容器存活探针：`python -m app.jobs.probe {scheduler|worker}`。

- `scheduler`：读 Redis 心跳键，超时即退出码 1（进程卡死或 Redis 失联）。
- `worker`：扫描 /proc 确认 arq worker 进程存在（容器内唯一的 arq 入口），
  避免只看 Redis 就误判「队列可达 = worker 活着」。

退出码 0 表示存活。Compose 的 healthcheck 与本文件是同一份判据。
"""

import asyncio
import os
import sys
import time

from redis.asyncio import Redis

from app.config import get_settings
from app.jobs.scheduler import HEARTBEAT_KEY

WORKER_MARKER = "app.jobs.worker.WorkerSettings"


def _worker_process_alive() -> bool:
    self_pid = os.getpid()
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) == self_pid:
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as handle:
                cmdline = handle.read().replace(b"\x00", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if WORKER_MARKER in cmdline:
            return True
    return False


async def _scheduler_alive() -> bool:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)
    try:
        raw = await redis.get(HEARTBEAT_KEY)
    finally:
        await redis.aclose()
    if raw is None:
        return False
    age = int(time.time()) - int(raw)
    return age <= settings.scheduler_heartbeat_timeout_seconds


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in {"scheduler", "worker"}:
        print("usage: python -m app.jobs.probe {scheduler|worker}", file=sys.stderr)
        return 2
    if args[0] == "scheduler":
        return 0 if asyncio.run(_scheduler_alive()) else 1
    return 0 if _worker_process_alive() else 1


if __name__ == "__main__":
    sys.exit(main())

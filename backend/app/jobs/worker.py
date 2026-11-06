"""arq worker 入口：`arq app.jobs.worker.WorkerSettings`（Compose `worker` 服务）。

S2 只提供一条无副作用的 `ping` 任务，用来证明「入队 → 出队 → 执行」链路可用；
真正的采集与扫描任务在 S3 起按 `docs/plan/p1.md` 加入 `functions`。
"""

import logging
from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.config import get_settings
from app.jobs.keys import canonical_job_key

logger = logging.getLogger(__name__)


async def ping(ctx: dict[str, Any], payload: dict[str, Any] | None = None) -> str:
    """链路自检任务：不读写业务数据，只回显。"""

    job_key = canonical_job_key("ping", payload)
    logger.info("ping job executed: job_key=%s job_id=%s", job_key, ctx.get("job_id"))
    return "pong"


class WorkerSettings:
    """arq 的 worker 配置对象（arq 按类属性读取）。"""

    functions: ClassVar[list[Any]] = [ping]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 3
    job_timeout = 300
    keep_result = 3600

"""路由依赖：数据库会话与任务投递。"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.jobs.queue import enqueue_task

SessionDep = AsyncIterator[AsyncSession]


async def session_dep() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


async def dispatch(task_name: str, **kwargs: object) -> str | None:
    """任务投递（测试可覆盖此依赖，避免真连 Redis）。"""

    return await enqueue_task(task_name, **kwargs)


__all__ = ["dispatch", "session_dep"]

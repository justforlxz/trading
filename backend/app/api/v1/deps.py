"""路由依赖：数据库会话、OKX 客户端、真实行情源与任务投递。

外部 HTTP 只通过 adapters 创建，路由层不直接 import httpx。
"""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.equity.registry import build_equity_source
from app.adapters.okx.client import OkxClient
from app.config import get_settings
from app.db.session import get_session
from app.jobs.queue import enqueue_task
from app.ports.market_data import EquitySource

SessionDep = AsyncIterator[AsyncSession]


async def session_dep() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


def okx_client() -> OkxClient:
    settings = get_settings()
    return OkxClient(
        settings.okx_rest_base_url,
        settings.okx_http_timeout_seconds,
        candles_rate_limit=settings.okx_candles_rate_limit,
        history_rate_limit=settings.okx_history_rate_limit,
        window_seconds=settings.okx_rate_limit_window_seconds,
        max_retries=settings.okx_max_retries,
        backoff_seconds=settings.okx_retry_backoff_seconds,
    )


def equity_source(request: Request) -> EquitySource:
    settings = get_settings()
    return build_equity_source(
        settings.equity_source, timeout_seconds=settings.equity_http_timeout_seconds
    )


async def dispatch(task_name: str, **kwargs: object) -> str | None:
    """任务投递（测试可覆盖此依赖，避免真连 Redis）。"""

    return await enqueue_task(task_name, **kwargs)


__all__ = ["dispatch", "equity_source", "okx_client", "session_dep"]

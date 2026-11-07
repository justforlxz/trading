"""回测测试夹具：库准备、表清理与可注入的任务投递。"""

import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.market.conftest import MARKET_TABLES, _database_url

BACKEND_DIR = Path(__file__).resolve().parents[2]
BACKTEST_TABLES = (
    "backtest.backtest_trade",
    "backtest.backtest_equity_point",
    "backtest.backtest_metric",
    "backtest.backtest_run",
    "strategy.strategy_transition",
    "strategy.strategy_approval",
    "strategy.strategy_leg",
    "strategy.strategy",
)

TRUNCATE_SQL = f"TRUNCATE {', '.join((*BACKTEST_TABLES, *MARKET_TABLES))} RESTART IDENTITY CASCADE"

# 子进程完成建库 + 迁移：不碰当前进程的事件循环，避免影响后续目录的 async 用例。
PREPARE_SNIPPET = """
import asyncio
import os
import subprocess
import sys

import asyncpg

url = sys.argv[1]
backend_dir = sys.argv[2]
dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
base, _, name = dsn.rpartition("/")
name = name.split("?", 1)[0]


async def create() -> None:
    connection = await asyncpg.connect(f"{base}/postgres")
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", name
        )
        if not exists:
            await connection.execute(f'CREATE DATABASE "{name}"')
    finally:
        await connection.close()


asyncio.run(create())
subprocess.run(
    [sys.executable, "-m", "alembic", "upgrade", "head"],
    cwd=backend_dir,
    env={**os.environ, "DATABASE_URL": url},
    check=True,
)
"""


def _prepare_database_blocking(url: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", PREPARE_SNIPPET, url, str(BACKEND_DIR)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:  # pragma: no cover - 环境故障
        raise RuntimeError(f"prepare test database failed: {result.stderr}")


@pytest.fixture(scope="session")
def database_url() -> str:
    """测试库 URL；建库与迁移在子进程完成。"""

    url = _database_url()
    if not url:
        pytest.skip("未配置 TEST_DATABASE_URL / DATABASE_URL: 跳过数据库用例")
    _prepare_database_blocking(url)
    return url


@pytest_asyncio.fixture(autouse=True)
async def clean_database(database_url: str) -> None:
    from app.db import session as db_session

    async with db_session.session_factory() as db:
        await db.execute(text(TRUNCATE_SQL))
        await db.commit()


@pytest_asyncio.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    from app.db import session as db_session

    async with db_session.session_factory() as db:
        yield db


@pytest.fixture
def dispatched() -> list[dict[str, Any]]:
    """记录被投递的任务参数；测试自己决定何时同步执行。"""

    return []


@pytest.fixture
async def client(
    dispatched: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    """不连 Redis 的 API 客户端：`dispatch` 只记录，不真的入队。"""

    from app.api.v1 import backtest as backtest_api
    from app.main import create_app

    app = create_app()

    async def fake_dispatch(task_name: str, **kwargs: object) -> str | None:
        dispatched.append({"task_name": task_name, **kwargs})
        return "test-arq-job"

    monkeypatch.setattr(backtest_api, "dispatch", fake_dispatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as api:
        yield api

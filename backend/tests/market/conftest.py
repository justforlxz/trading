"""market 测试夹具：测试库准备、表清理与真实录制 fixture 读取。

数据库 URL 由 `tests/conftest.py` 在导入 app 前确定（默认 `trading_test`）。
建库与迁移放在同步 session 级夹具里，用 `asyncio.run` / `subprocess` 完成，
避免 pytest-asyncio 的 function 级事件循环与 session 级异步夹具冲突。
"""

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

BACKEND_DIR = Path(__file__).resolve().parents[2]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

MARKET_TABLES = (
    "market.candle",
    "market.equity_candle",
    "market.equity_asset",
    "market.instrument",
    "market.market_session",
    "market.data_source_sync",
    "market.data_quality_issue",
    "market.basis_snapshot",
    "ops.job_run",
    "ops.audit_log",
)

TRUNCATE_SQL = f"TRUNCATE {', '.join(MARKET_TABLES)} RESTART IDENTITY CASCADE"


def load_fixture(name: str) -> dict[str, Any]:
    """读取真实录制的原始响应（含 `_meta` 抓取时间与来源）。"""

    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _database_url() -> str | None:
    return os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")


def _asyncpg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _split_database(url: str) -> tuple[str, str]:
    """拆出管理库 DSN 与目标库名。"""

    base, _, name = _asyncpg_url(url).rpartition("/")
    return f"{base}/postgres", name.split("?", 1)[0]


async def _create_database_if_missing(url: str) -> None:
    admin_dsn, name = _split_database(url)
    connection = await asyncpg.connect(admin_dsn)
    try:
        exists = await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if not exists:
            await connection.execute(f'CREATE DATABASE "{name}"')
    finally:
        await connection.close()


def _prepare_database(url: str) -> None:
    asyncio.run(_create_database_if_missing(url))
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": url},
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session")
def database_url() -> str:
    """测试库 URL；未配置数据库时跳过依赖库的用例。"""

    url = _database_url()
    if not url:
        pytest.skip("未配置 TEST_DATABASE_URL / DATABASE_URL: 跳过数据库用例")
    # 迁移在子进程/新循环里执行，会清掉当前事件循环；留下可用的循环，
    # 保证其它测试目录排在后面时 async 用例依然能拿到 loop。
    try:
        previous = asyncio.get_event_loop_policy().get_event_loop()
    except RuntimeError:
        previous = None
    _prepare_database(url)
    if previous is not None and not previous.is_closed():
        asyncio.set_event_loop(previous)
    else:
        asyncio.set_event_loop(asyncio.new_event_loop())
    return url


@pytest_asyncio.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    """每个用例前清空业务表（整个测试会话共用一个事件循环）。"""

    from app.db import session as db_session

    async with db_session.session_factory() as db:
        await db.execute(text(TRUNCATE_SQL))
        await db.commit()
        yield db

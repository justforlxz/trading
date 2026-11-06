"""research 测试夹具：复用 market 的库准备，并把 research 表一起清空。"""

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.market.conftest import MARKET_TABLES, _database_url, _prepare_database

RESEARCH_TABLES = (
    "research.relation_edge",
    "research.relation_snapshot",
    "research.relative_strength_snapshot",
    "research.target_symbol",
)

TRUNCATE_SQL = f"TRUNCATE {', '.join((*RESEARCH_TABLES, *MARKET_TABLES))} RESTART IDENTITY CASCADE"


@pytest.fixture(scope="session")
def database_url() -> str:
    """测试库 URL；建库与迁移复用 market 夹具的实现。

    该准备过程内部用 `asyncio.run`，会清空当前线程的事件循环。若此前
    已经存在 session 级事件循环（例如 market 用例先跑），必须把它恢复，
    否则后续异步用例会报 “There is no current event loop”。
    """

    url = _database_url()
    if not url:
        pytest.skip("未配置 TEST_DATABASE_URL / DATABASE_URL: 跳过数据库用例")
    try:
        previous = asyncio.get_event_loop_policy().get_event_loop()
    except RuntimeError:
        previous = None
    _prepare_database(url)
    if previous is not None and not previous.is_closed():
        asyncio.set_event_loop(previous)
    return url


@pytest_asyncio.fixture(autouse=True)
async def clean_database(database_url: str) -> None:
    """每个用例前清空行情与 research 业务表，避免只读用例相互污染。"""

    from app.db import session as db_session

    async with db_session.session_factory() as db:
        await db.execute(text(TRUNCATE_SQL))
        await db.commit()


@pytest_asyncio.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    """供造数与断言使用的会话（整个测试会话共用一个事件循环）。"""

    from app.db import session as db_session

    async with db_session.session_factory() as db:
        yield db

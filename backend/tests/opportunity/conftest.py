"""opportunity 测试夹具：复用 market 的库准备，并把机会与截面表一起清空。"""

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.market.conftest import MARKET_TABLES, _database_url, _prepare_database

OPPORTUNITY_TABLES = (
    "opportunity.cluster_member",
    "opportunity.opportunity",
    "opportunity.asset_cluster",
    "opportunity.opportunity_run",
    "research.market_snapshot",
)

TRUNCATE_SQL = (
    f"TRUNCATE {', '.join((*OPPORTUNITY_TABLES, *MARKET_TABLES))} RESTART IDENTITY CASCADE"
)


@pytest.fixture(scope="session")
def database_url() -> str:
    """测试库 URL；建库与迁移复用 market 夹具的实现（会清空当前事件循环）。"""

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
    from app.db import session as db_session

    async with db_session.session_factory() as db:
        await db.execute(text(TRUNCATE_SQL))
        await db.commit()


@pytest_asyncio.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    from app.db import session as db_session

    async with db_session.session_factory() as db:
        yield db

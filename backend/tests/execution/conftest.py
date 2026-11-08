"""执行层测试夹具：复用风控播种器，额外清理 execution 表并重置 paper 撮合状态。"""

import subprocess
import sys
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.market.conftest import MARKET_TABLES, _database_url
from tests.risk.conftest import (
    DEFAULT_CAPITAL,
    DEFAULT_LEGS,
    PREPARE_SNIPPET,
    RISK_TABLES,
    Seeded,
    seed_strategy,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]

EXECUTION_TABLES = (
    "execution.reconcile_diff",
    "execution.fill",
    'execution."order"',
    "execution.position",
)
TRUNCATE_SQL = (
    f"TRUNCATE {', '.join((*EXECUTION_TABLES, *RISK_TABLES, *MARKET_TABLES))} "
    "RESTART IDENTITY CASCADE"
)


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


@pytest_asyncio.fixture(autouse=True)
def reset_paper() -> AsyncIterator[None]:
    """每个用例从空模拟交易所开始；执行后同样清空，避免互相污染。"""

    from app.execution import paper

    paper.reset_paper_source()
    yield
    paper.reset_paper_source()


@pytest_asyncio.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    from app.db import session as db_session

    async with db_session.session_factory() as db:
        yield db


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as api:
        yield api


async def seed_execution_strategy(session: AsyncSession, **kwargs):
    """播种一只可通过风控的组合：净值走平（回撤 0），单腿权重 0.15。

    风控默认 `max_order_notional=20000`（本金 10 万 → 单腿权重上限 0.2）、
    `max_concentration=0.5`，因此不能用风控夹具的 0.6 单腿权重。
    """

    capital = kwargs.pop("capital", DEFAULT_CAPITAL)
    if "legs" not in kwargs:
        kwargs["legs"] = (
            ("BTC-USDT-SWAP", "long", Decimal("0.15")),
            ("ETH-USDT-SWAP", "short", Decimal("0.15")),
        )
    kwargs.setdefault("equity", (capital, capital))
    return await seed_strategy(session, capital=capital, **kwargs)


__all__ = [
    "DEFAULT_CAPITAL",
    "DEFAULT_LEGS",
    "Seeded",
    "client",
    "database_url",
    "seed_execution_strategy",
    "session",
]

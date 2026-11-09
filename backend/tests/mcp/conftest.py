"""MCP 测试夹具：测试库准备、全业务表清理、客户端签发与 JSON-RPC 调用辅助。"""

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.market.conftest import MARKET_TABLES, _database_url
from tests.risk.conftest import _prepare_database_blocking

# MCP 用例横跨全部业务域，因此整库清理，避免上个用例的残留把行数断言带偏。
MCP_TABLES = (
    "mcp.mcp_call_log",
    "mcp.mcp_clients",
    "execution.reconcile_diff",
    "execution.fill",
    'execution."order"',
    "execution.position",
    "risk.risk_event",
    "risk.risk_policy",
    "backtest.backtest_trade",
    "backtest.backtest_equity_point",
    "backtest.backtest_metric",
    "backtest.backtest_run",
    "strategy.strategy_transition",
    "strategy.strategy_approval",
    "strategy.strategy_leg",
    "strategy.strategy",
    "opportunity.cluster_member",
    "opportunity.opportunity",
    "opportunity.asset_cluster",
    "opportunity.opportunity_run",
    "research.relative_strength_snapshot",
    "research.relation_edge",
    "research.relation_snapshot",
    "research.target_symbol",
    "research.market_snapshot",
)

TRUNCATE_SQL = f"TRUNCATE {', '.join((*MCP_TABLES, *MARKET_TABLES))} RESTART IDENTITY CASCADE"


@pytest.fixture(scope="session")
def database_url() -> str:
    """建库与迁移在子进程完成：不碰当前进程的事件循环（见 tests/risk/conftest.py）。"""

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


# ---------------------------------------------------------------------------
# 客户端签发与调用辅助
# ---------------------------------------------------------------------------


async def issue_client(
    session: AsyncSession, *, scopes: tuple[str, ...] = ("read",), name: str = "test-agent"
):
    from app.mcp import service as mcp_service

    return await mcp_service.create_client(session, name=name, scopes=list(scopes))


@pytest_asyncio.fixture
async def read_token(session: AsyncSession) -> str:
    _client, token = await issue_client(session, scopes=("read",), name="reader")
    return token


@pytest_asyncio.fixture
async def operate_token(session: AsyncSession) -> str:
    _client, token = await issue_client(session, scopes=("read", "operate"), name="operator")
    return token


def auth(token: str | None) -> dict[str, str]:
    return {} if token is None else {"Authorization": f"Bearer {token}"}


async def rpc(
    client: AsyncClient,
    token: str | None,
    message: Any,
    *,
    accept: str | None = None,
) -> Response:
    headers = auth(token)
    if accept:
        headers["Accept"] = accept
    return await client.post("/mcp", json=message, headers=headers)


async def rpc_request(
    client: AsyncClient,
    token: str | None,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    request_id: int | str = 1,
    accept: str | None = None,
) -> Response:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return await rpc(client, token, message, accept=accept)


async def call_tool(
    client: AsyncClient,
    token: str | None,
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    accept: str | None = None,
) -> Response:
    return await rpc_request(
        client,
        token,
        "tools/call",
        {"name": name, "arguments": arguments or {}},
        accept=accept,
    )


def tool_payload(response: Response) -> Any:
    """取出 `tools/call` 的 JSON 载荷（content[0].text 反序列化）。"""

    body = response.json()
    assert "result" in body, body
    assert body["result"]["isError"] is False, body["result"]
    return json.loads(body["result"]["content"][0]["text"])


def tool_error_code(response: Response) -> str:
    body = response.json()
    assert "result" in body, body
    assert body["result"]["isError"] is True, body["result"]
    return json.loads(body["result"]["content"][0]["text"])["error"]["code"]

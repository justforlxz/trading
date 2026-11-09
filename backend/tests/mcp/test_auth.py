"""MCP 鉴权与 scope（AC-1 / AC-2）。

AC-1：无 token / 错 token / 吊销后的 token 一律 401。
AC-2：read scope 调操作类工具返回 403，且业务表行数不变（无副作用）。
"""

from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp import service as mcp_service
from app.mcp.auth import hash_token
from app.mcp.models import McpCallLog, McpClient
from tests.mcp.conftest import call_tool, issue_client, rpc_request

BUSINESS_TABLES = (
    "strategy.strategy",
    "strategy.strategy_leg",
    "strategy.strategy_transition",
    "opportunity.opportunity_run",
    "opportunity.opportunity",
    'execution."order"',
    "execution.position",
    "backtest.backtest_run",
    "ops.job_run",
)

OPERATE_CALLS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("trigger_scan", {"idempotency_key": "deny-1", "reason": "deny probe"}),
    (
        "create_strategy_draft",
        {
            "kind": "relative_value",
            "name": "denied draft",
            "templates": ["relative_value"],
            "reason": "deny probe",
        },
    ),
    ("update_strategy_draft", {"strategy_id": 1, "reason": "deny probe"}),
    (
        "run_backtest",
        {
            "strategy_id": 1,
            "window": {"start": "2026-01-01T00:00:00Z", "end": "2026-02-01T00:00:00Z"},
            "reason": "deny probe",
        },
    ),
    ("submit_strategy_for_approval", {"strategy_id": 1, "reason": "deny probe"}),
    ("pause_strategy", {"strategy_id": 1, "reason": "deny probe"}),
    ("resume_strategy", {"strategy_id": 1, "reason": "deny probe"}),
    (
        "execute_strategy_action",
        {
            "strategy_id": 1,
            "action": "open",
            "reason": "deny probe",
            "inst_id": "BTC-USDT-SWAP",
            "side": "buy",
            "quantity": "1",
        },
    ),
)


async def _counts(session: AsyncSession) -> dict[str, int]:
    return {
        table: int(await session.scalar(text(f"SELECT count(*) FROM {table}")) or 0)
        for table in BUSINESS_TABLES
    }


async def test_missing_token_returns_401(client) -> None:
    response = await rpc_request(client, None, "ping")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "mcp_unauthorized"
    assert "result" not in body


async def test_wrong_token_returns_401(client) -> None:
    response = await rpc_request(client, "definitely-not-a-token", "ping")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "mcp_unauthorized"


async def test_malformed_authorization_header_returns_401(client) -> None:
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Authorization": "Basic abc"},
    )
    assert response.status_code == 401


async def test_revoked_token_stops_working_immediately(client, session) -> None:
    _client, token = await issue_client(session, scopes=("operate",), name="revoked")
    assert (await rpc_request(client, token, "ping")).status_code == 200

    row = (
        await session.execute(select(McpClient).where(McpClient.token_hash == hash_token(token)))
    ).scalar_one()
    await mcp_service.revoke_client(session, row.id)

    after = await rpc_request(client, token, "ping")
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "mcp_unauthorized"


async def test_valid_token_updates_last_used_at(client, session) -> None:
    row, token = await issue_client(session, scopes=("read",), name="usage")
    assert row.last_used_at is None

    assert (await rpc_request(client, token, "ping")).status_code == 200

    refreshed = await session.get(McpClient, row.id)
    await session.refresh(refreshed)
    assert refreshed.last_used_at is not None


@pytest.mark.parametrize(("name", "arguments"), OPERATE_CALLS)
async def test_read_scope_is_rejected_on_every_operate_tool(
    client, read_token: str, name: str, arguments: dict[str, Any]
) -> None:
    response = await call_tool(client, read_token, name, arguments)
    assert response.status_code == 403
    body = response.json()
    # HTTP 状态是 403，报文仍是 JSON-RPC 错误；具体业务码在 data 里。
    assert body["error"]["code"] == -32003
    assert body["error"]["data"]["code"] == "mcp_forbidden"
    assert body["error"]["data"]["scope"] == "operate"
    assert body["error"]["data"]["scopes"] == ["read"]


async def test_read_scope_attempts_have_no_business_side_effects(
    client, session, read_token: str
) -> None:
    before = await _counts(session)

    for name, arguments in OPERATE_CALLS:
        response = await call_tool(client, read_token, name, arguments)
        assert response.status_code == 403

    assert await _counts(session) == before

    # 被拒绝的调用仍然留审计（AC-8），但那是审计表，不是业务副作用。
    denied = list(
        (await session.scalars(select(McpCallLog).where(McpCallLog.status == "denied"))).all()
    )
    assert len(denied) == len(OPERATE_CALLS)
    assert {row.error_code for row in denied} == {"mcp_forbidden"}

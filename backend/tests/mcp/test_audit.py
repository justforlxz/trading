"""调用审计（AC-8）：每次 MCP 调用都有记录，操作类带 reason。"""

from sqlalchemy import select

from app.mcp.auth import hash_token
from app.mcp.models import McpCallLog, McpClient
from tests.mcp.conftest import call_tool, issue_client, rpc_request, tool_error_code


async def _logs(session) -> list[McpCallLog]:
    return list((await session.scalars(select(McpCallLog).order_by(McpCallLog.id))).all())


async def test_every_rpc_call_writes_a_log_row(client, session, read_token: str) -> None:
    row = (
        await session.execute(
            select(McpClient).where(McpClient.token_hash == hash_token(read_token))
        )
    ).scalar_one()

    await rpc_request(client, read_token, "ping")
    await rpc_request(client, read_token, "tools/list")
    await call_tool(client, read_token, "market_status", {})

    logs = await _logs(session)
    assert [entry.tool for entry in logs] == ["ping", "tools/list", "market_status"]
    assert {entry.client_id for entry in logs} == {row.id}
    assert {entry.status for entry in logs} == {"ok"}
    assert all(entry.latency_ms >= 0 for entry in logs)
    assert all(len(entry.args_digest) == 64 for entry in logs)
    # 只读调用没有 reason。
    assert {entry.reason for entry in logs} == {None}


async def test_operate_call_records_reason_and_error_code(
    client, session, operate_token: str
) -> None:
    response = await call_tool(
        client,
        operate_token,
        "pause_strategy",
        {"strategy_id": 7, "reason": "maintenance window"},
    )
    assert tool_error_code(response) == "not_live_authorized"

    log = (await _logs(session))[-1]
    assert log.tool == "pause_strategy"
    assert log.status == "error"
    assert log.error_code == "not_live_authorized"
    assert log.reason == "maintenance window"


async def test_operate_call_without_reason_is_audited_as_error(
    client, session, operate_token: str
) -> None:
    response = await call_tool(
        client, operate_token, "trigger_scan", {"idempotency_key": "no-reason"}
    )
    assert response.json()["result"]["isError"] is True

    log = (await _logs(session))[-1]
    assert log.tool == "trigger_scan"
    assert log.status == "error"
    assert log.error_code == "reason_required"
    assert log.reason is None


async def test_args_digest_is_stable_and_does_not_leak_arguments(
    client, session, read_token: str
) -> None:
    await call_tool(client, read_token, "get_strategy", {"strategy_id": 42})
    await call_tool(client, read_token, "get_strategy", {"strategy_id": 42})
    await call_tool(client, read_token, "get_strategy", {"strategy_id": 43})

    first, second, third = (await _logs(session))[-3:]
    assert first.args_digest == second.args_digest
    assert first.args_digest != third.args_digest
    # 摘要里不含明文参数值。
    assert "42" not in first.args_digest
    assert "43" not in third.args_digest


async def test_each_client_is_tracked_separately(client, session) -> None:
    _read_client, read_token = await issue_client(session, scopes=("read",), name="reader-a")
    _op_client, op_token = await issue_client(
        session, scopes=("read", "operate"), name="operator-b"
    )

    await rpc_request(client, read_token, "ping")
    await call_tool(client, op_token, "market_status", {})

    logs = await _logs(session)
    assert len(logs) == 2
    assert logs[0].client_id != logs[1].client_id
    names = {row.id: row.name for row in (await session.scalars(select(McpClient))).all()}
    assert {names[log.client_id] for log in logs} == {"reader-a", "operator-b"}

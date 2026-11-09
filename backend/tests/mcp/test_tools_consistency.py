"""工具面一致性（AC-3）与工具清单的硬边界（AC-5 负向断言）。"""

from typing import Any

from sqlalchemy import select, text

from app.mcp.models import McpCallLog
from tests.mcp.conftest import call_tool, rpc_request, tool_payload
from tests.strategy.test_api import _create, _seed_target

FORBIDDEN_TOOL_NAMES = (
    "place_order",
    "approve_strategy",
    "live_authorize",
    "toggle_live_trading",
    "set_risk_limit",
)


def _read_only_tool_names() -> set[str]:
    from app.mcp.tools import TOOLS

    return {tool.name for tool in TOOLS if tool.scope == "read"}


def _operate_tool_names() -> set[str]:
    from app.mcp.tools import TOOLS

    return {tool.name for tool in TOOLS if tool.scope == "operate"}


async def test_ac3_get_strategy_is_field_identical_to_web_api(
    client, session, read_token: str
) -> None:
    """同一 strategy_id，MCP `get_strategy` 与 Web API 逐项一致。"""

    target = await _seed_target(session)
    created = (await _create(client, target.id)).json()
    strategy_id = created["id"]
    await client.post(f"/api/v1/strategies/{strategy_id}/submit")

    web = await client.get(f"/api/v1/strategies/{strategy_id}")
    assert web.status_code == 200

    mcp = await call_tool(client, read_token, "get_strategy", {"strategy_id": strategy_id})
    assert mcp.status_code == 200
    payload = tool_payload(mcp)

    assert payload == web.json()
    # 逐项比对（dict 相等已覆盖，这里给出显式证据：字段集合与关键值）。
    assert set(payload) == set(web.json())
    assert payload["status"] == "pending_approval"
    assert payload["legs"] == web.json()["legs"]
    assert payload["transitions"] == web.json()["transitions"]


async def test_ac5_tool_list_excludes_authorization_and_naked_order_tools(
    client, read_token: str
) -> None:
    response = await rpc_request(client, read_token, "tools/list")
    names = [tool["name"] for tool in response.json()["result"]["tools"]]

    for forbidden in FORBIDDEN_TOOL_NAMES:
        assert forbidden not in names
    assert not [name for name in names if name.startswith("approve_")]
    assert not [name for name in names if name.startswith("toggle_live_")]
    assert not [name for name in names if name.startswith("live_authorize")]

    # 工具清单里既有只读面也有受控操作面，但没有任何裸下单入口。
    assert {"market_status", "list_opportunities", "get_strategy"} <= set(names)
    assert {"trigger_scan", "execute_strategy_action"} <= set(names)
    assert "place_order" not in _operate_tool_names() | _read_only_tool_names()


async def test_operate_tools_all_demand_a_reason(client, operate_token: str) -> None:
    """操作类工具没有 reason 时拒绝，且不落业务数据。"""

    from app.mcp.tools import TOOLS

    for tool in TOOLS:
        if tool.scope != "operate":
            continue
        assert "reason" in tool.input_schema["properties"], tool.name
        assert "reason" in tool.input_schema["required"], tool.name

    response = await call_tool(
        client, operate_token, "trigger_scan", {"idempotency_key": "no-reason"}
    )
    body = response.json()["result"]
    assert body["isError"] is True
    assert "reason_required" in body["content"][0]["text"]


async def test_tool_reads_do_not_write_business_tables(client, session, read_token: str) -> None:
    target = await _seed_target(session)
    created = (await _create(client, target.id)).json()
    strategy_id = created["id"]

    before: dict[str, Any] = {
        table: int(await session.scalar(text(f"SELECT count(*) FROM {table}")) or 0)
        for table in ("strategy.strategy", "strategy.strategy_leg", "opportunity.opportunity")
    }

    for name, arguments in (
        ("list_strategies", {}),
        ("get_strategy", {"strategy_id": strategy_id}),
        ("risk_status", {"strategy_id": strategy_id}),
        ("list_positions", {}),
        ("list_orders", {}),
        ("virtual_positions", {}),
        ("market_status", {}),
    ):
        response = await call_tool(client, read_token, name, arguments)
        assert response.json()["result"]["isError"] is False, (name, response.text)

    after = {
        table: int(await session.scalar(text(f"SELECT count(*) FROM {table}")) or 0)
        for table in before
    }
    assert after == before

    logged = list((await session.scalars(select(McpCallLog).order_by(McpCallLog.id))).all())
    assert [row.tool for row in logged] == [
        "list_strategies",
        "get_strategy",
        "risk_status",
        "list_positions",
        "list_orders",
        "virtual_positions",
        "market_status",
    ]
    assert {row.status for row in logged} == {"ok"}

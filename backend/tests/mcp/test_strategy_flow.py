"""策略草稿流程（AC-5）：create -> update -> submit 后进入 pending_approval。"""

from app.strategy.models import Strategy
from tests.mcp.conftest import call_tool, tool_payload
from tests.strategy.test_api import _seed_target


async def test_ac5_draft_flow_reaches_pending_approval(client, session, operate_token: str) -> None:
    target = await _seed_target(session)

    created = tool_payload(
        await call_tool(
            client,
            operate_token,
            "create_strategy_draft",
            {
                "kind": "relative_value",
                "name": "mcp draft",
                "target_id": target.id,
                "templates": ["relative_value"],
                "reason": "external agent proposes a pair",
            },
        )
    )
    assert created["created"] is True
    strategy = created["strategy"]
    assert strategy["status"] == "draft"
    assert len(strategy["legs"]) == 2
    strategy_id = strategy["id"]

    updated = tool_payload(
        await call_tool(
            client,
            operate_token,
            "update_strategy_draft",
            {
                "strategy_id": strategy_id,
                "name": "mcp draft v2",
                "reason": "rename before review",
            },
        )
    )
    assert updated["name"] == "mcp draft v2"
    assert updated["version"] == strategy["version"] + 1
    assert updated["status"] == "draft"

    submitted = tool_payload(
        await call_tool(
            client,
            operate_token,
            "submit_strategy_for_approval",
            {"strategy_id": strategy_id, "reason": "ready for human review"},
        )
    )
    assert submitted["status"] == "pending_approval"
    assert submitted["transitions"][-1]["actor"] == "mcp:operator"
    assert submitted["transitions"][-1]["reason"] == "ready for human review"

    stored = await session.get(Strategy, strategy_id)
    assert stored is not None
    assert stored.status == "pending_approval"


async def test_draft_update_is_rejected_once_submitted(client, session, operate_token: str) -> None:
    target = await _seed_target(session)
    strategy_id = tool_payload(
        await call_tool(
            client,
            operate_token,
            "create_strategy_draft",
            {
                "kind": "relative_value",
                "name": "frozen",
                "target_id": target.id,
                "templates": ["relative_value"],
                "reason": "draft",
            },
        )
    )["strategy"]["id"]

    await call_tool(
        client,
        operate_token,
        "submit_strategy_for_approval",
        {"strategy_id": strategy_id, "reason": "submit"},
    )

    response = await call_tool(
        client,
        operate_token,
        "update_strategy_draft",
        {"strategy_id": strategy_id, "name": "late edit", "reason": "too late"},
    )
    body = response.json()["result"]
    assert body["isError"] is True
    assert "strategy_readonly" in body["content"][0]["text"]

    stored = await session.get(Strategy, strategy_id)
    await session.refresh(stored)
    assert stored.name == "frozen"


async def test_submit_never_approves_a_strategy(client, session, operate_token: str) -> None:
    """MCP 只能把策略送到 pending_approval：状态不会越过人工审批。"""

    target = await _seed_target(session)
    strategy_id = tool_payload(
        await call_tool(
            client,
            operate_token,
            "create_strategy_draft",
            {
                "kind": "relative_value",
                "name": "needs-human",
                "target_id": target.id,
                "templates": ["relative_value"],
                "reason": "draft",
            },
        )
    )["strategy"]["id"]

    tool_payload(
        await call_tool(
            client,
            operate_token,
            "submit_strategy_for_approval",
            {"strategy_id": strategy_id, "reason": "submit"},
        )
    )

    stored = await session.get(Strategy, strategy_id)
    await session.refresh(stored)
    assert stored.status == "pending_approval"
    assert stored.approved_at is None

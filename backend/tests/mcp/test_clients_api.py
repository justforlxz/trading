"""Web 端的 MCP 客户端管理接口：生成 / 列表 / 吊销（设置页用）。"""

from tests.mcp.conftest import call_tool, rpc_request


async def test_create_returns_token_exactly_once(client) -> None:
    response = await client.post(
        "/api/v1/mcp/clients", json={"name": "laptop agent", "scopes": ["read"]}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["client"]["name"] == "laptop agent"
    assert body["client"]["scopes"] == ["read"]
    assert body["client"]["revoked"] is False
    assert body["client"]["last_used_at"] is None
    token = body["token"]
    assert isinstance(token, str)
    assert len(token) >= 32

    listed = await client.get("/api/v1/mcp/clients")
    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["id"] == body["client"]["id"]
    assert item["scopes"] == ["read"]
    assert "token" not in item
    assert "token_hash" not in item


async def test_scopes_are_normalized_and_deduplicated(client) -> None:
    response = await client.post(
        "/api/v1/mcp/clients",
        json={"name": "operator", "scopes": ["operate", "read", "operate"]},
    )
    assert response.status_code == 201
    assert response.json()["client"]["scopes"] == ["read", "operate"]


async def test_invalid_scope_is_rejected(client) -> None:
    response = await client.post("/api/v1/mcp/clients", json={"name": "bad", "scopes": ["admin"]})
    assert response.status_code == 422


async def test_revoke_makes_token_stop_working(client) -> None:
    created = (
        await client.post(
            "/api/v1/mcp/clients", json={"name": "temp", "scopes": ["read", "operate"]}
        )
    ).json()
    token = created["token"]
    client_id = created["client"]["id"]

    assert (await rpc_request(client, token, "ping")).status_code == 200

    revoked = await client.delete(f"/api/v1/mcp/clients/{client_id}")
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] is True
    assert revoked.json()["revoked_at"]

    assert (await rpc_request(client, token, "ping")).status_code == 401


async def test_revoke_is_idempotent(client) -> None:
    created = (
        await client.post("/api/v1/mcp/clients", json={"name": "twice", "scopes": ["read"]})
    ).json()
    client_id = created["client"]["id"]

    first = await client.delete(f"/api/v1/mcp/clients/{client_id}")
    second = await client.delete(f"/api/v1/mcp/clients/{client_id}")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["revoked_at"] == second.json()["revoked_at"]


async def test_revoke_unknown_client_is_404(client) -> None:
    response = await client.delete("/api/v1/mcp/clients/999999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "mcp_client_not_found"


async def test_api_created_client_can_call_tools(client, session) -> None:
    created = (
        await client.post(
            "/api/v1/mcp/clients", json={"name": "web-made", "scopes": ["read", "operate"]}
        )
    ).json()
    token = created["token"]

    response = await call_tool(client, token, "market_status", {})
    assert response.json()["result"]["isError"] is False


async def test_operate_only_client_can_still_read(client, session) -> None:
    """operate 覆盖 read：只读工具对 operate 客户端可用。"""

    created = (
        await client.post("/api/v1/mcp/clients", json={"name": "op-only", "scopes": ["operate"]})
    ).json()

    read_response = await call_tool(client, created["token"], "market_status", {})
    assert read_response.json()["result"]["isError"] is False


async def test_read_only_client_cannot_operate(client, session) -> None:
    created = (
        await client.post("/api/v1/mcp/clients", json={"name": "ro", "scopes": ["read"]})
    ).json()

    response = await call_tool(
        client,
        created["token"],
        "trigger_scan",
        {"idempotency_key": "ro", "reason": "probe"},
    )
    assert response.status_code == 403


async def test_issued_clients_are_listed_newest_first(client) -> None:
    first = (
        await client.post("/api/v1/mcp/clients", json={"name": "first", "scopes": ["read"]})
    ).json()
    second = (
        await client.post("/api/v1/mcp/clients", json={"name": "second", "scopes": ["read"]})
    ).json()

    listed = (await client.get("/api/v1/mcp/clients")).json()["items"]
    assert [item["id"] for item in listed][:2] == [
        second["client"]["id"],
        first["client"]["id"],
    ]

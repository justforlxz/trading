"""JSON-RPC 2.0 传输契约：notification、错误码、batch 与 SSE。"""

import json
from typing import Any

from tests.mcp.conftest import call_tool, rpc, rpc_request


async def test_initialize_reports_protocol_and_capabilities(client, read_token: str) -> None:
    response = await rpc_request(
        client, read_token, "initialize", {"protocolVersion": "2024-11-05"}
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["protocolVersion"]
    assert result["serverInfo"]["name"] == "trading-mcp"
    assert "tools" in result["capabilities"]
    assert "resources" in result["capabilities"]


async def test_ping_returns_empty_result(client, read_token: str) -> None:
    response = await rpc_request(client, read_token, "ping")
    assert response.status_code == 200
    assert response.json()["result"] == {}


async def test_notification_returns_202_with_empty_body(client, read_token: str) -> None:
    response = await rpc(
        client, read_token, {"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert response.status_code == 202
    assert response.content == b""


async def test_unknown_method_is_method_not_found(client, read_token: str) -> None:
    response = await rpc_request(client, read_token, "no/such/method")
    assert response.status_code == 200
    error = response.json()["error"]
    assert error["code"] == -32601
    assert "no/such/method" in error["message"]


async def test_unknown_tool_is_invalid_params(client, read_token: str) -> None:
    response = await call_tool(client, read_token, "place_order", {"inst_id": "BTC-USDT-SWAP"})
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32602


async def test_tools_call_without_name_is_invalid_params(client, read_token: str) -> None:
    response = await rpc_request(client, read_token, "tools/call", {"arguments": {}})
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32602


async def test_invalid_json_is_parse_error(client, read_token: str) -> None:
    response = await client.post(
        "/mcp",
        content=b"{not json",
        headers={
            "Authorization": f"Bearer {read_token}",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32700


async def test_batch_returns_array_of_responses(client, read_token: str) -> None:
    batch: list[dict[str, Any]] = [
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    response = await rpc(client, read_token, batch)
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert [item["id"] for item in body] == [1, 2]
    assert body[1]["result"]["tools"]


async def test_empty_batch_is_invalid_request(client, read_token: str) -> None:
    response = await rpc(client, read_token, [])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32600


async def test_sse_response_wraps_payload_in_message_event(client, read_token: str) -> None:
    response = await rpc_request(client, read_token, "ping", accept="text/event-stream")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert text.startswith("event: message\ndata: ")
    payload = json.loads(text[len("event: message\ndata: ") :].strip())
    assert payload["id"] == 1
    assert payload["result"] == {}


async def test_tools_list_shape_matches_mcp_contract(client, read_token: str) -> None:
    response = await rpc_request(client, read_token, "tools/list")
    tools = response.json()["result"]["tools"]
    assert tools
    for tool in tools:
        assert set(tool) == {"name", "description", "inputSchema"}
        assert tool["inputSchema"]["type"] == "object"
        assert "properties" in tool["inputSchema"]

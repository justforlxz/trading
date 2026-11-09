"""`trading-mcp` stdio 包装器：只转发，不在本地算业务。"""

import json

import httpx
import pytest

from app.mcp import stdio


def test_target_config_defaults(monkeypatch) -> None:
    for key in ("TRADING_MCP_URL", "TRADING_MCP_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    assert stdio.target_config() == (stdio.DEFAULT_URL, "")

    monkeypatch.setenv("TRADING_MCP_URL", "http://example.test/mcp")
    monkeypatch.setenv("TRADING_MCP_TOKEN", "abc")
    assert stdio.target_config() == ("http://example.test/mcp", "abc")


async def test_forward_posts_jsonrpc_with_bearer_token() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})

    reply = await stdio.forward(
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        url="http://example.test/mcp",
        token="secret",
        transport=httpx.MockTransport(handler),
    )

    assert captured["method"] == "POST"
    assert captured["url"] == "http://example.test/mcp"
    assert captured["authorization"] == "Bearer secret"
    assert captured["body"] == {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    assert reply == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}


async def test_forward_returns_none_for_notification_202() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202)

    reply = await stdio.forward(
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        url="http://example.test/mcp",
        token="secret",
        transport=httpx.MockTransport(handler),
    )
    assert reply is None


def test_main_requires_a_token(monkeypatch, capsys) -> None:
    monkeypatch.delenv("TRADING_MCP_TOKEN", raising=False)
    assert stdio.main(["--url", "http://example.test/mcp"]) == 2
    captured = capsys.readouterr()
    assert "TRADING_MCP_TOKEN" in captured.err


@pytest.mark.parametrize("token", ["", "   "])
def test_main_rejects_blank_token(monkeypatch, capsys, token: str) -> None:
    monkeypatch.delenv("TRADING_MCP_TOKEN", raising=False)
    assert stdio.main(["--token", token]) == 2
    assert "TRADING_MCP_TOKEN" in capsys.readouterr().err

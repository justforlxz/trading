"""MCP resources：清单与按 URI 读取。"""

import json

from tests.mcp.conftest import rpc_request
from tests.strategy.test_api import _create, _seed_target


async def test_resources_list_exposes_the_three_uris(client, read_token: str) -> None:
    response = await rpc_request(client, read_token, "resources/list")
    resources = response.json()["result"]["resources"]
    uris = [item["uri"] for item in resources]
    assert "market://snapshot" in uris
    assert "strategy://{id}" in uris
    assert "backtest://{id}" in uris
    for item in resources:
        assert set(item) == {"uri", "name", "description", "mimeType"}
        assert item["mimeType"] == "application/json"


async def test_strategy_resource_matches_web_detail(client, session, read_token: str) -> None:
    target = await _seed_target(session)
    strategy_id = (await _create(client, target.id)).json()["id"]
    web = (await client.get(f"/api/v1/strategies/{strategy_id}")).json()

    response = await rpc_request(
        client, read_token, "resources/read", {"uri": f"strategy://{strategy_id}"}
    )
    contents = response.json()["result"]["contents"]
    assert len(contents) == 1
    assert contents[0]["uri"] == f"strategy://{strategy_id}"
    assert contents[0]["mimeType"] == "application/json"
    assert json.loads(contents[0]["text"]) == web


async def test_market_snapshot_resource_returns_empty_state_without_scan(
    client, read_token: str
) -> None:
    response = await rpc_request(client, read_token, "resources/read", {"uri": "market://snapshot"})
    payload = json.loads(response.json()["result"]["contents"][0]["text"])
    assert payload["as_of"] is None
    assert payload["count"] == 0
    assert payload["items"] == []


async def test_backtest_resource_returns_metrics(client, session, read_token: str) -> None:
    from decimal import Decimal

    from app.backtest.models import BacktestMetric
    from tests.execution.conftest import seed_execution_strategy

    seeded = await seed_execution_strategy(session)
    assert seeded.run_id is not None
    session.add(
        BacktestMetric(run_id=seeded.run_id, name="sharpe", value=Decimal("1.5"), unit="ratio")
    )
    await session.commit()

    response = await rpc_request(
        client, read_token, "resources/read", {"uri": f"backtest://{seeded.run_id}"}
    )
    payload = json.loads(response.json()["result"]["contents"][0]["text"])
    assert payload["id"] == seeded.run_id
    assert payload["strategy_id"] == seeded.strategy_id
    assert payload["status"] == "ok"
    assert payload["metrics"][0]["name"] == "sharpe"
    assert Decimal(payload["metrics"][0]["value"]) == Decimal("1.5")


async def test_unknown_resource_uri_is_invalid_params(client, read_token: str) -> None:
    response = await rpc_request(client, read_token, "resources/read", {"uri": "nope://1"})
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32602


async def test_resource_needs_a_valid_token(client) -> None:
    response = await client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "resources/list"}
    )
    assert response.status_code == 401

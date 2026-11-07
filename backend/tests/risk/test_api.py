"""风控 API 用例（P2-07）：6 个端点、错误信封与任务幂等。"""

from typing import Any

import pytest

from app.adapters.okx.risk import MarketHealthQuote
from tests.risk.conftest import seed_strategy

THRESHOLDS: dict[str, str] = {
    "max_order_notional": "100000",
    "max_leg_weight": "0.6",
    "max_leverage": "1.0",
    "max_gross_exposure": "1.0",
    "max_net_exposure": "1.0",
    "max_instrument_weight": "0.6",
    "max_concentration": "0.5",
    "drawdown_warn": "0.05",
    "drawdown_reduce": "0.10",
    "drawdown_close": "0.20",
    "funding_rate_threshold": "0.0005",
    "min_depth_notional": "20000",
}

FUNDING_PAYLOAD: dict[str, Any] = {
    "data": [
        {
            "instId": "BTC-USDT-SWAP",
            "fundingRate": "0.0012",
            "nextFundingTime": "1735689600000",
        }
    ]
}
BOOK_PAYLOAD: dict[str, Any] = {"data": [{"bids": [["100", "5"]], "asks": [["100.1", "10"]]}]}


def _put_body(**overrides: Any) -> dict[str, Any]:
    thresholds = dict(THRESHOLDS)
    thresholds.update(overrides)
    return {
        "expected_version": 1,
        "updated_by": "pytest",
        "note": "pytest",
        "thresholds": thresholds,
    }


async def test_get_policy_bootstraps_version_one(client) -> None:
    response = await client.get("/api/v1/risk/policy")
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "global"
    assert body["version"] == 1
    assert set(body["thresholds"]) == set(THRESHOLDS)
    assert body["thresholds"]["max_concentration"] == "0.5"
    assert isinstance(body["thresholds"]["max_order_notional"], str)


async def test_put_policy_bumps_version(client) -> None:
    await client.get("/api/v1/risk/policy")
    response = await client.put("/api/v1/risk/policy", json=_put_body(max_concentration="0.4"))
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 2
    assert body["thresholds"]["max_concentration"] == "0.4"
    assert body["updated_by"] == "pytest"


async def test_put_policy_stale_version_conflicts(client) -> None:
    await client.get("/api/v1/risk/policy")
    await client.put("/api/v1/risk/policy", json=_put_body())
    stale = await client.put("/api/v1/risk/policy", json=_put_body())
    assert stale.status_code == 409
    error = stale.json()["error"]
    assert error["code"] == "risk_policy_stale"
    assert error["details"]["current_version"] == 2


async def test_put_policy_invalid_threshold_is_422(client) -> None:
    await client.get("/api/v1/risk/policy")
    response = await client.put(
        "/api/v1/risk/policy",
        json=_put_body(drawdown_warn="0.30", drawdown_reduce="0.10", drawdown_close="0.20"),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "risk_invalid_threshold"


async def test_put_policy_missing_threshold_is_risk_invalid_threshold(client) -> None:
    await client.get("/api/v1/risk/policy")
    body = _put_body()
    del body["thresholds"]["max_leverage"]
    response = await client.put("/api/v1/risk/policy", json=body)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "risk_invalid_threshold"
    assert error["details"]["missing"] == ["max_leverage"]


async def test_status_reports_breaches_without_events(client, session) -> None:
    seeded = await seed_strategy(session)
    response = await client.get("/api/v1/risk/status", params={"strategy_id": seeded.strategy_id})
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "strategy"
    assert body["strategy_id"] == seeded.strategy_id
    assert body["allowed"] is False
    codes = {item["code"] for item in body["breaches"]}
    assert "concentration_exceeded" in codes


async def test_events_endpoint_paginates(client, session) -> None:
    seeded = await seed_strategy(session)
    from app.risk import service

    await service.evaluate(session, strategy_id=seeded.strategy_id, evaluation_key="2026-11-07")

    response = await client.get("/api/v1/risk/events", params={"limit": 1})
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["next_cursor"] is not None

    next_page = await client.get(
        "/api/v1/risk/events", params={"limit": 1, "cursor": body["next_cursor"]}
    )
    assert next_page.status_code == 200
    assert next_page.json()["items"][0]["id"] != body["items"][0]["id"]


async def test_events_cursor_validation_uses_envelope(client) -> None:
    response = await client.get("/api/v1/risk/events", params={"cursor": "abc"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


async def test_funding_endpoint_returns_observations(
    client, session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import risk as risk_api

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def aclose(self) -> None:
            pass

    class FakeSource:
        def __init__(self, client: Any, *, book_depth: int = 20) -> None:
            pass

        async def observe(self, inst_id: str) -> MarketHealthQuote:
            return MarketHealthQuote(
                inst_id=inst_id,
                funding_payload={
                    **FUNDING_PAYLOAD,
                    "data": [{**FUNDING_PAYLOAD["data"][0], "instId": inst_id}],
                },
                book_payload=BOOK_PAYLOAD,
            )

    monkeypatch.setattr(risk_api, "OkxClient", FakeClient)
    monkeypatch.setattr(risk_api, "OkxRiskMarketSource", FakeSource)

    response = await client.get("/api/v1/risk/funding", params={"inst_ids": "BTC-USDT-SWAP"})
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["inst_id"] == "BTC-USDT-SWAP"
    assert [item["kind"] for item in body["breaches"]] == ["funding", "liquidity"]


async def test_funding_endpoint_missing_data_is_503(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import risk as risk_api

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def aclose(self) -> None:
            pass

    class FakeSource:
        def __init__(self, client: Any, *, book_depth: int = 20) -> None:
            pass

        async def observe(self, inst_id: str) -> None:
            return None

    monkeypatch.setattr(risk_api, "OkxClient", FakeClient)
    monkeypatch.setattr(risk_api, "OkxRiskMarketSource", FakeSource)

    response = await client.get("/api/v1/risk/funding", params={"inst_ids": "BTC-USDT-SWAP"})
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "risk_market_data_unavailable"
    assert error["details"]["missing"] == ["BTC-USDT-SWAP"]


async def test_evaluate_job_is_idempotent(client, session, dispatched) -> None:
    seeded = await seed_strategy(session)
    payload = {"strategy_id": seeded.strategy_id, "evaluation_key": "2026-11-07"}

    first = await client.post("/api/v1/risk/evaluate", json=payload)
    assert first.status_code == 202
    first_body = first.json()
    assert first_body["created"] is True
    assert first_body["dispatched"] is True
    assert first_body["run_id"] == first_body["job_id"]
    assert len(dispatched) == 1
    assert dispatched[0]["task_name"] == "risk_evaluate"
    assert dispatched[0]["strategy_id"] == seeded.strategy_id

    second = await client.post("/api/v1/risk/evaluate", json=payload)
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["run_id"] == first_body["run_id"]
    assert second_body["created"] is False
    assert second_body["dispatched"] is False
    assert len(dispatched) == 1


async def test_unknown_strategy_uses_envelope_not_500(client) -> None:
    response = await client.post("/api/v1/risk/evaluate", json={"strategy_id": 9999})
    assert response.status_code == 202

    status_response = await client.get("/api/v1/risk/status", params={"strategy_id": 9999})
    assert status_response.status_code == 404
    assert status_response.json()["error"]["code"] == "not_found"

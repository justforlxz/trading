"""风险事件只读端点：按实例过滤、总数与字段形状。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.instrument import sync_instruments
from app.risk import RiskContext, RiskEngine, TradeRequest
from tests.factories.instruments import make_ref

D = Decimal
NOW = datetime(2026, 11, 13, 2, 0, tzinfo=UTC)


def test_risk_event_endpoint_lists_persisted_rejections(client: TestClient) -> None:
    sync_instruments([make_ref()])
    rejected = RiskEngine().authorize(
        TradeRequest(
            instance_id="si_1",
            inst_id="XAAPL-USDT",
            side="buy",
            order_type="limit",
            qty=D("100"),
            price=D("100"),
            ts=NOW,
        ),
        RiskContext(equity=D("10000"), available_balance=D("10000")),
    )
    assert not rejected.allowed

    response = client.get("/api/risk/events", params={"instance_id": "si_1"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == len(rejected.violations) > 0
    first = body["items"][0]
    assert first["event_id"].startswith("re_")
    assert first["instance_id"] == "si_1"
    assert first["inst_id"] == "XAAPL-USDT"
    assert first["rule"] in {item.rule for item in rejected.violations}
    assert first["detail"]
    assert first["created_at"] == "2026-11-13T02:00:00Z"
    assert first["resolved_at"] is None


def test_risk_event_endpoint_filters_by_rule_and_limit(client: TestClient) -> None:
    sync_instruments([make_ref()])
    for instance_id in ("si_1", "si_2"):
        RiskEngine().authorize(
            TradeRequest(
                instance_id=instance_id,
                inst_id="XAAPL-USDT",
                side="buy",
                order_type="limit",
                qty=D("100"),
                price=D("100"),
                ts=NOW,
            ),
            RiskContext(equity=D("10000"), available_balance=D("10000")),
        )

    response = client.get("/api/risk/events", params={"limit": 1})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 1
    assert body["total"] > 1

    filtered = client.get("/api/risk/events", params={"rule": "order_amount_ratio"})

    assert filtered.status_code == 200, filtered.text
    rules = {item["rule"] for item in filtered.json()["items"]}
    assert rules == {"order_amount_ratio"}


def test_risk_event_endpoint_documents_rule_applicability(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "/api/risk/events" in schema["paths"]
    assert "RiskEventListResponse" in schema["components"]["schemas"]
    assert "RiskEvent" in schema["components"]["schemas"]

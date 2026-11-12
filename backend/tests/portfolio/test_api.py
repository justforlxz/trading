"""组合接口：列表、明细、敞口、申请与批准。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.routes import portfolio as portfolio_routes
from app.instrument import sync_instruments
from app.portfolio import (
    record_allocation,
    record_fill,
)
from tests.factories.instruments import make_ref

D = Decimal
TARGET = {
    "legs": [
        {
            "inst_id": "BTC-USDT",
            "inst_type": "SPOT",
            "direction": "long",
            "target_weight": "0.25",
        }
    ],
    "net_exposure": "0.25",
}


@pytest.fixture()
def instance(client: TestClient) -> str:
    sync_instruments(
        [
            make_ref(inst_id="BTC-USDT", base_ccy="BTC", inst_category="1"),
            make_ref(inst_id="ETH-USDT", base_ccy="ETH", inst_category="1"),
        ]
    )
    created = client.post(
        "/api/strategy-instances",
        json={
            "strategy_id": "relative_value",
            "name": "BTC/ETH 配对",
            "bar": "1d",
            "inst_ids": ["BTC-USDT", "ETH-USDT"],
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()["instance_id"])


def test_portfolio_list_and_detail_are_served_from_the_real_ledger(
    client: TestClient, instance: str
) -> None:
    record_allocation(instance, capital_budget=D("1000"), priority=5)
    record_fill(instance, inst_id="BTC-USDT", side="buy", qty=D("2"), price=D("100"))

    listed = client.get("/api/portfolio/strategies")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["instance_id"] == instance
    assert row["capital_budget"] == "1000"
    assert row["priority"] == 5
    assert row["gross_exposure"] == "200"
    assert row["net_exposure"] == "200"
    assert row["open_positions"] == 1

    detail = client.get(f"/api/portfolio/strategies/{instance}")
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["portfolio"] == row
    assert payload["target"] is None
    position = payload["positions"][0]
    assert position["inst_id"] == "BTC-USDT"
    assert position["product_key"] == "BTC"
    assert position["direction"] == "long"
    assert position["qty"] == "2"
    assert position["avg_cost"] == "100"
    assert position["unit"] == "base"


def test_missing_instance_is_404(client: TestClient, instance: str) -> None:
    assert client.get("/api/portfolio/strategies/si_missing").status_code == 404


def test_exposure_endpoint_lists_conflicts_with_both_sides(
    client: TestClient, instance: str
) -> None:
    second = client.post(
        "/api/strategy-instances",
        json={
            "strategy_id": "relative_value",
            "name": "反向",
            "bar": "1d",
            "inst_ids": ["BTC-USDT", "ETH-USDT"],
        },
    ).json()["instance_id"]
    record_fill(instance, inst_id="BTC-USDT", side="buy", qty=D("1"), price=D("100"))
    record_fill(second, inst_id="BTC-USDT", side="sell", qty=D("1"), price=D("100"))

    response = client.get("/api/portfolio/exposure")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["conflicts"] == [
        {"product_key": "BTC", "long_instance_ids": [instance], "short_instance_ids": [second]}
    ]
    assert body["open_positions"] == 2
    assert body["product_count"] == 1
    assert body["net_exposure"] == "0"


def test_adjustment_flow_over_http(client: TestClient, instance: str) -> None:
    """申请 → 未生效 → 批准 → 生效；批准人与时间都在响应里。"""

    created = client.post(
        "/api/portfolio/adjustments",
        json={
            "instance_id": instance,
            "requested_by": "lxz",
            "target": TARGET,
            "note": "提高 BTC 权重",
        },
    )
    assert created.status_code == 201, created.text
    record = created.json()
    assert record["status"] == "pending"
    assert record["decided_by"] is None
    assert record["target"] == {
        **TARGET,
        "legs": [{**TARGET["legs"][0], "qty": None, "unit": None}],
    }

    detail = client.get(f"/api/portfolio/strategies/{instance}").json()
    assert detail["target"] is None

    decided = client.patch(
        f"/api/portfolio/adjustments/{record['adjustment_id']}",
        json={"decision": "approved", "decided_by": "reviewer", "note": "同意"},
    )
    assert decided.status_code == 200, decided.text
    approved = decided.json()
    assert approved["status"] == "approved"
    assert approved["decided_by"] == "reviewer"
    assert approved["decided_at"] is not None
    assert approved["note"] == "同意"

    detail = client.get(f"/api/portfolio/strategies/{instance}").json()
    assert detail["target"] == record["target"]

    listed = client.get("/api/portfolio/adjustments")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["adjustment_id"] == record["adjustment_id"]


def test_adjustment_for_a_missing_instance_is_400(client: TestClient, instance: str) -> None:
    response = client.post(
        "/api/portfolio/adjustments",
        json={"instance_id": "si_missing", "requested_by": "lxz", "target": TARGET},
    )

    assert response.status_code == 400


def test_unknown_adjustment_is_404(client: TestClient, instance: str) -> None:
    response = client.patch(
        "/api/portfolio/adjustments/adj_missing",
        json={"decision": "approved", "decided_by": "reviewer"},
    )
    assert response.status_code == 404


def test_trade_ledger_does_not_touch_account_positions(
    client: TestClient, instance: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两层持仓不混用：组合端点不导入、也不调用执行域的持仓模块。"""

    record_fill(instance, inst_id="BTC-USDT", side="buy", qty=D("1"), price=D("100"))
    client.get("/api/portfolio/exposure")

    assert not hasattr(portfolio_routes, "AccountPosition")

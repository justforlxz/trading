"""Trades 只读端点：没有执行快照时也要给出可读的空状态，不返回 501。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.instrument import sync_instruments
from tests.factories.instruments import make_ref


def test_journal_is_readable_before_any_trade(client: TestClient) -> None:
    response = client.get("/api/journal")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "manual"
    assert body["strategies"] == []
    assert body["positions"] == []
    assert body["orders"] == []
    assert body["fills"] == []
    assert body["signals"] == []
    assert body["items"] == []
    assert body["total"] == 0


def test_journal_lists_a_strategy_without_backtest_or_fills(client: TestClient) -> None:
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
            "name": "空仓策略",
            "bar": "1h",
            "params": {},
            "inst_ids": ["BTC-USDT", "ETH-USDT"],
        },
    )
    assert created.status_code == 201, created.text
    instance_id = created.json()["instance_id"]

    body = client.get("/api/journal").json()
    strategy = next(item for item in body["strategies"] if item["instance_id"] == instance_id)

    assert strategy["expected_return"] is None
    assert strategy["expected_source"] == "backtest:none"
    assert strategy["actual_return"] == "0"
    assert strategy["actual_source"] == "execution:no_fills"
    assert strategy["strategy_version"] == created.json()["strategy_version"]

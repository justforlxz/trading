"""OKX 标的与 K 线同步入口：产品路径、任务流水、失败与参数校验。

假 OKX 通过注入的行情适配器接入，测试不连真实上游。断言只看能从库里重新读出的
事实：标的行、已落库 K 线、`data_sync_jobs` 与健康接口的读取结果。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.exchange import create_market_data
from app.jobs import sync as okx_jobs
from app.market import latest_sync_job, load_candles, start_sync_job


@pytest.fixture()
def fake_okx(monkeypatch: pytest.MonkeyPatch, fake_okx_settings: Settings) -> Iterator[None]:
    """把同步入口构造的行情适配器指向线程内假 OKX。"""

    def _market_data(*, settings: Settings | None = None, transport: object = None):
        return create_market_data(settings=fake_okx_settings, transport=transport)

    monkeypatch.setattr(okx_jobs, "create_market_data", _market_data)
    yield


def _sync_instruments(client: TestClient) -> dict:
    response = client.post("/api/system/sync", json={"dataset": "instruments"})
    assert response.status_code == 202, response.text
    return response.json()


def test_instrument_sync_fills_both_categories(client: TestClient, fake_okx: None) -> None:
    body = _sync_instruments(client)

    assert body["status"] == "succeeded"
    assert body["rows"] > 0
    assert body["error"] is None

    items = client.get("/api/instruments/search", params={"q": "aapl"}).json()["items"]
    assert {"AAPL-USDT-SWAP", "XAAPL-USDT"} <= {item["inst_id"] for item in items}

    job = latest_sync_job(provider="okx", dataset="instruments")
    assert job is not None
    assert job.id == body["job_id"]
    assert job.status == "succeeded"
    assert job.rows == body["rows"]

    health = client.get("/api/system/health").json()
    okx = next(item for item in health["components"] if item["name"] == "okx_rest")
    assert okx["status"] == "ok"
    assert "instruments" in okx["detail"]


def test_candle_sync_writes_real_history_for_requested_symbol(
    client: TestClient, fake_okx: None
) -> None:
    _sync_instruments(client)

    response = client.post(
        "/api/system/sync",
        json={"dataset": "candles", "instrument_ids": ["XAAPL-USDT"], "bar": "1d", "days": 5},
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["rows"] > 0

    candles = load_candles("XAAPL-USDT", "1d", source="okx_spot")
    assert candles
    assert all(candle.confirm for candle in candles)

    series = client.get(
        "/api/instruments/XAAPL-USDT/candles",
        params={"bar": "1d", "source": "okx_spot", "limit": 10},
    )
    assert series.status_code == 200
    assert series.json()["candles"]


def test_candle_sync_uses_swap_source_for_perpetual(client: TestClient, fake_okx: None) -> None:
    _sync_instruments(client)

    response = client.post(
        "/api/system/sync",
        json={"dataset": "candles", "instrument_ids": ["AAPL-USDT-SWAP"], "days": 3},
    )

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "succeeded"
    assert load_candles("AAPL-USDT-SWAP", "1d", source="okx_swap")


def test_candle_sync_defaults_to_subscribed_instruments(client: TestClient, fake_okx: None) -> None:
    _sync_instruments(client)
    saved = client.patch(
        "/api/settings",
        json={"data_sources": {"subscribed_instruments": ["AAPL"]}},
    )
    assert saved.status_code == 200, saved.text

    response = client.post("/api/system/sync", json={"dataset": "candles", "days": 3})

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "succeeded"
    assert load_candles("XAAPL-USDT", "1d", source="okx_spot")
    assert load_candles("AAPL-USDT-SWAP", "1d", source="okx_swap")


def test_candle_sync_rejects_unknown_symbol_before_job(client: TestClient, fake_okx: None) -> None:
    response = client.post(
        "/api/system/sync",
        json={"dataset": "candles", "instrument_ids": ["NOPE-USDT"]},
    )

    assert response.status_code == 400
    assert "未找到标的" in response.json()["detail"]
    assert latest_sync_job(provider="okx", dataset="candles") is None


def test_candle_sync_rejects_bar_or_days_for_instruments(
    client: TestClient, fake_okx: None
) -> None:
    response = client.post(
        "/api/system/sync",
        json={"dataset": "instruments", "days": 5},
    )

    assert response.status_code == 400
    assert "bar 或 days" in response.json()["detail"]


def test_upstream_failure_is_recorded_and_health_stale(
    client: TestClient, fake_okx: None, fake_okx_server
) -> None:
    fake_okx_server.scenarios.activate("upstream_error")

    response = client.post("/api/system/sync", json={"dataset": "instruments"})

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"]

    job = latest_sync_job(provider="okx", dataset="instruments")
    assert job is not None
    assert job.status == "failed"
    assert job.error == body["error"]

    health = client.get("/api/system/health").json()
    okx = next(item for item in health["components"] if item["name"] == "okx_rest")
    assert okx["status"] == "stale"
    assert okx["error"] == body["error"]


def test_running_job_returns_conflict(client: TestClient) -> None:
    start_sync_job("okx", "candles")

    response = client.post("/api/system/sync", json={"dataset": "candles"})

    assert response.status_code == 409
    assert "仍在运行" in response.json()["detail"]


def test_unknown_dataset_lists_only_the_okx_datasets(client: TestClient) -> None:
    response = client.post("/api/system/sync", json={"dataset": "unknown"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "instruments" in detail
    assert "candles" in detail
    assert "market_overview" not in detail
    assert "news" not in detail

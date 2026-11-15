"""设置端点：四类设置、分组更新、密钥只写不读与数据源同步状态。"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.market import finish_sync_job, start_sync_job

UTC_ZULU = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

DEFAULT_DISPLAY = {
    "color_scheme": "system",
    "default_bar": "1d",
    "price_precision": 2,
    "home_layout": "cockpit",
}
DEFAULT_RISK_DEFAULTS = {
    "default_leverage": "3",
    "risk_budget_per_trade": "100",
    "warning_threshold": "80",
    "stop_rule": "fixed_pct",
}


@pytest.fixture(autouse=True)
def _clean_credentials(monkeypatch: pytest.MonkeyPatch):
    """隔离本机环境：默认没有 API Key、Secret 与 Passphrase。"""

    monkeypatch.setenv("OKX_API_KEY", "")
    monkeypatch.setenv("OKX_SECRET_KEY", "")
    monkeypatch.setenv("OKX_PASSPHRASE", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_get_returns_v6_defaults_and_hides_internal_groups(client: TestClient) -> None:
    response = client.get("/api/settings")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["display"] == DEFAULT_DISPLAY
    assert body["risk_defaults"] == DEFAULT_RISK_DEFAULTS
    assert body["execution"] == {"auto_trading_enabled": False}
    assert body["data_sources"] == {
        "provider": None,
        "subscribed_instruments": [],
        "last_sync_at": None,
        "failure_count": 0,
    }
    assert body["secrets"] == {
        "okx_api_key_masked": None,
        "okx_configured": False,
        "okx_permission": None,
    }
    assert UTC_ZULU.match(body["updated_at"]) is not None
    for removed in ("risk", "costs", "backtest", "data", "exchange"):
        assert removed not in body

    again = client.get("/api/settings").json()
    assert again["updated_at"] == body["updated_at"]


def test_patch_updates_each_group_and_persists(client: TestClient) -> None:
    response = client.patch(
        "/api/settings",
        json={
            "display": {
                "color_scheme": "dark",
                "default_bar": "4h",
                "price_precision": 4,
                "home_layout": "compact",
            },
            "risk_defaults": {
                "default_leverage": "5",
                "risk_budget_per_trade": "250",
                "warning_threshold": "70",
                "stop_rule": "atr",
            },
            "execution": {"auto_trading_enabled": True},
            "data_sources": {
                "provider": "fake",
                "subscribed_instruments": ["BTC-USDT", "AAPL-USDT-SWAP"],
            },
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["display"]["color_scheme"] == "dark"
    assert body["display"]["default_bar"] == "4h"
    assert body["risk_defaults"]["default_leverage"] == "5"
    assert body["execution"]["auto_trading_enabled"] is True
    assert body["data_sources"]["provider"] == "fake"
    assert body["data_sources"]["subscribed_instruments"] == [
        "BTC-USDT",
        "AAPL-USDT-SWAP",
    ]

    again = client.get("/api/settings").json()
    assert again["display"] == body["display"]
    assert again["risk_defaults"] == body["risk_defaults"]
    assert again["execution"] == body["execution"]


def test_patch_requires_at_least_one_group(client: TestClient) -> None:
    response = client.patch("/api/settings", json={})

    assert response.status_code == 422


def test_patch_rejects_removed_groups_and_fields(client: TestClient) -> None:
    for payload in (
        {"mode": "live"},
        {"execution": {"mode": "live"}},
        {"costs": {"taker_fee_bps": "5"}},
        {"backtest": {"default_bar": "1h"}},
        {"data": {"proxy_enabled": True}},
        {"secrets": {"okx_api_key_masked": "x"}},
    ):
        assert client.patch("/api/settings", json=payload).status_code == 422, payload


def test_risk_default_bounds_are_validated(client: TestClient) -> None:
    response = client.patch("/api/settings", json={"risk_defaults": {"default_leverage": "20"}})

    assert response.status_code == 422


def test_api_key_is_write_only_and_never_echoed(client: TestClient) -> None:
    secret = "api-key-plain-value"

    response = client.patch("/api/settings", json={"exchange": {"api_key": secret}})

    assert response.status_code == 200, response.text
    assert secret not in response.text
    body = response.json()
    assert body["secrets"]["okx_configured"] is True
    assert body["secrets"]["okx_api_key_masked"] == "********"
    assert body["secrets"]["okx_permission"] == "unknown"
    assert "exchange" not in body


def test_secret_and_passphrase_never_appear_in_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OKX_SECRET_KEY", "secret-value")
    monkeypatch.setenv("OKX_PASSPHRASE", "passphrase-value")
    get_settings.cache_clear()

    response = client.get("/api/settings")

    assert "secret-value" not in response.text
    assert "passphrase-value" not in response.text


def test_data_source_status_comes_from_sync_jobs(client: TestClient) -> None:
    succeeded = start_sync_job("fake", "market_overview")
    finish_sync_job(succeeded.id, "succeeded", rows=4)
    failed = start_sync_job("fake", "news")
    finish_sync_job(failed.id, "failed", error="Provider 超时")
    client.patch("/api/settings", json={"data_sources": {"provider": "fake"}})

    body = client.get("/api/settings").json()

    assert body["data_sources"]["provider"] == "fake"
    assert body["data_sources"]["last_sync_at"] is not None
    assert body["data_sources"]["failure_count"] == 1


def test_api_key_from_environment_is_reported_as_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OKX_API_KEY", "env-key-value")
    get_settings.cache_clear()

    body = client.get("/api/settings").json()

    assert body["secrets"]["okx_configured"] is True
    assert body["secrets"]["okx_api_key_masked"] == "********"
    assert "env-key-value" not in str(body)

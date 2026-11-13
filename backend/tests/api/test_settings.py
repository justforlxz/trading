"""设置端点：分组读写、凭据只写不读、实盘二次确认。

每个用例使用独立 schema；凭据相关的环境变量在用例内显式清空或设置，不依赖本机
`.env` 里是否恰好有 OKX API Key。
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

UTC_ZULU = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

DEFAULT_RISK = {
    "max_order_notional": "1000",
    "max_position_notional": "3000",
    "max_total_notional": "10000",
    "max_positions": 5,
    "max_leverage": "3",
    "max_daily_loss": "300",
    "liquidation_buffer_pct": "10",
    "stop_loss_mandatory": True,
}
DEFAULT_COSTS = {
    "maker_fee_bps": "2",
    "taker_fee_bps": "5",
    "slippage_bps": "3",
    "spread_bps": "2",
}
DEFAULT_BACKTEST = {
    "funding_enabled": True,
    "default_initial_capital": "10000",
    "default_bar": "1h",
}


@pytest.fixture(autouse=True)
def _clean_credentials(monkeypatch: pytest.MonkeyPatch):
    """隔离本机环境：默认没有 API Key，交易所演示盘打开。"""

    monkeypatch.setenv("OKX_API_KEY", "")
    monkeypatch.setenv("OKX_DEMO", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_get_returns_defaults(client: TestClient) -> None:
    """首次读取返回默认文档，并写入稳定的 updated_at。"""

    response = client.get("/api/settings")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["execution"] == {
        "mode": "paper",
        "auto_trading_enabled": False,
        "emergency_stop": False,
    }
    assert body["risk"] == DEFAULT_RISK
    assert body["costs"] == DEFAULT_COSTS
    assert body["backtest"] == DEFAULT_BACKTEST
    assert body["data"] == {"proxy_enabled": False, "proxy_configured": False}
    assert body["exchange"] == {
        "demo_trading": True,
        "api_configured": False,
        "api_key_masked": None,
    }
    assert UTC_ZULU.match(body["updated_at"]) is not None

    again = client.get("/api/settings").json()
    assert again["updated_at"] == body["updated_at"]


def test_put_updates_each_group(client: TestClient) -> None:
    """分组级部分更新只改提交的分组，未提交的保持原值。"""

    payload = {
        "risk": {**DEFAULT_RISK, "max_order_notional": "1234", "max_leverage": "5"},
        "costs": {**DEFAULT_COSTS, "taker_fee_bps": "7"},
        "backtest": {**DEFAULT_BACKTEST, "default_bar": "4h"},
        "data": {"proxy_enabled": True, "proxy_configured": True},
    }
    response = client.put("/api/settings", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["risk"]["max_order_notional"] == "1234"
    assert body["risk"]["max_leverage"] == "5"
    assert body["costs"]["taker_fee_bps"] == "7"
    assert body["backtest"]["default_bar"] == "4h"
    assert body["data"] == {"proxy_enabled": True, "proxy_configured": True}
    assert body["execution"]["mode"] == "paper"


def test_switch_to_live_without_ack_is_409_and_changes_nothing(client: TestClient) -> None:
    """未带 acknowledge_risk 切实盘返回 409，所有分组逐字段不变。"""

    before = client.get("/api/settings").json()
    response = client.put(
        "/api/settings",
        json={
            "execution": {
                "mode": "live",
                "auto_trading_enabled": False,
                "emergency_stop": False,
            },
            "risk": {**DEFAULT_RISK, "max_order_notional": "9999"},
        },
    )

    assert response.status_code == 409, response.text
    assert "acknowledge_risk" in response.json()["detail"]
    assert client.get("/api/settings").json() == before


def test_switch_to_live_with_ack_succeeds(client: TestClient) -> None:
    """带 acknowledge_risk=true 时切实盘成功，读回也是实盘。"""

    response = client.put(
        "/api/settings",
        json={
            "execution": {
                "mode": "live",
                "auto_trading_enabled": True,
                "emergency_stop": False,
            },
            "acknowledge_risk": True,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["execution"]["mode"] == "live"
    assert client.get("/api/settings").json()["execution"]["mode"] == "live"


def test_api_key_is_write_only(client: TestClient) -> None:
    """API Key 写入后只返回掩码与已配置状态，明文不出现在任何响应里。"""

    secret = "test-okx-api-key-write-only"
    response = client.put("/api/settings", json={"exchange": {"api_key": secret}})

    assert response.status_code == 200, response.text
    assert secret not in response.text
    body = response.json()
    assert body["exchange"]["api_configured"] is True
    assert body["exchange"]["api_key_masked"] == "********"
    assert get_settings().okx_api_key == secret

    fetched = client.get("/api/settings")
    assert secret not in fetched.text
    assert fetched.json()["exchange"]["api_configured"] is True
    assert fetched.json()["exchange"]["api_key_masked"] == "********"


def test_env_api_key_is_reported_but_never_returned(client: TestClient) -> None:
    """环境变量里的凭据只用于回答「已配置」，响应里没有明文。"""

    secret = "test-env-okx-api-key"
    get_settings().okx_api_key = secret

    response = client.get("/api/settings")

    assert response.status_code == 200
    assert secret not in response.text
    assert response.json()["exchange"]["api_configured"] is True
    assert response.json()["exchange"]["api_key_masked"] == "********"


def test_leverage_above_hard_limit_is_422(client: TestClient) -> None:
    """风控硬上限 10 不因配置抬高。"""

    response = client.put(
        "/api/settings",
        json={"risk": {**DEFAULT_RISK, "max_leverage": "11"}},
    )

    assert response.status_code == 422, response.text


def test_unknown_group_is_422(client: TestClient) -> None:
    """分组级更新不接受未知字段，避免拼写错误被静默忽略。"""

    response = client.put("/api/settings", json={"overview": {}})

    assert response.status_code == 422, response.text

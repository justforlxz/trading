"""设置端点：五类设置、分组更新、密钥只写不读、通知通道与投递台账。"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.events import DeliveryResult, DomainEvent, record_delivery
from app.jobs import OKX_PROVIDER
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
DEFAULT_NOTIFICATIONS = {
    "channels": ["browser"],
    "telegram": {"chat_id": "", "token_configured": False},
    "webhook": {"url": "", "secret_configured": False},
}


@pytest.fixture(autouse=True)
def _clean_credentials(monkeypatch: pytest.MonkeyPatch):
    """隔离本机环境：默认没有 API Key、Secret、Passphrase 与通知通道凭据。"""

    monkeypatch.setenv("OKX_API_KEY", "")
    monkeypatch.setenv("OKX_SECRET_KEY", "")
    monkeypatch.setenv("OKX_PASSPHRASE", "")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("WEBHOOK_SIGNING_SECRET", "")
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
        "subscribed_instruments": [],
        "last_sync_at": None,
        "failure_count": 0,
    }
    assert body["notifications"] == DEFAULT_NOTIFICATIONS
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
    assert "provider" not in body["data_sources"]
    assert body["data_sources"]["subscribed_instruments"] == [
        "BTC-USDT",
        "AAPL-USDT-SWAP",
    ]

    again = client.get("/api/settings").json()
    assert again["display"] == body["display"]
    assert again["risk_defaults"] == body["risk_defaults"]
    assert again["execution"] == body["execution"]


def test_notification_channels_can_be_turned_off_and_back_on(client: TestClient) -> None:
    """通知通道开关存在设置文档里；关掉后不再有通道，打开后恢复。"""

    off = client.patch("/api/settings", json={"notifications": {"channels": []}})

    assert off.status_code == 200, off.text
    assert off.json()["notifications"]["channels"] == []
    assert client.get("/api/settings").json()["notifications"]["channels"] == []

    on = client.patch(
        "/api/settings",
        json={"notifications": {"channels": ["browser", "telegram", " "]}},
    )

    assert on.status_code == 200, on.text
    assert on.json()["notifications"]["channels"] == ["browser", "telegram"]


def test_telegram_and_webhook_receivers_are_editable_and_persist(client: TestClient) -> None:
    """接收方是非敏感值：可读写、可保存；通道开关与接收方互不覆盖。"""

    saved = client.patch(
        "/api/settings",
        json={
            "notifications": {
                "channels": ["browser", "telegram", "webhook"],
                "telegram": {"chat_id": "-1001234567890"},
                "webhook": {"url": "https://example.invalid/hooks/trading"},
            }
        },
    )

    assert saved.status_code == 200, saved.text
    body = saved.json()["notifications"]
    assert body["channels"] == ["browser", "telegram", "webhook"]
    assert body["telegram"]["chat_id"] == "-1001234567890"
    assert body["webhook"]["url"] == "https://example.invalid/hooks/trading"

    # 只改通道开关：接收方保持原值，不被空默认值冲掉。
    channels_only = client.patch(
        "/api/settings", json={"notifications": {"channels": ["telegram"]}}
    )

    assert channels_only.status_code == 200, channels_only.text
    after = channels_only.json()["notifications"]
    assert after["channels"] == ["telegram"]
    assert after["telegram"]["chat_id"] == "-1001234567890"
    assert after["webhook"]["url"] == "https://example.invalid/hooks/trading"


def test_webhook_url_must_be_http_or_https(client: TestClient) -> None:
    response = client.patch(
        "/api/settings", json={"notifications": {"webhook": {"url": "ftp://example.invalid"}}}
    )

    assert response.status_code == 422


def test_empty_notification_group_is_rejected(client: TestClient) -> None:
    assert client.patch("/api/settings", json={"notifications": {}}).status_code == 422


def test_patch_applies_notification_channels_to_the_running_registry(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC4：保存通道开关时通知正在运行的通道注册表，不需要重启进程。"""

    applied: list[list[str]] = []
    monkeypatch.setattr("app.api.routes.settings.apply_channels", applied.append)

    response = client.patch("/api/settings", json={"notifications": {"channels": []}})

    assert response.status_code == 200, response.text
    assert applied == [[]]


def test_editing_only_a_receiver_does_not_touch_the_channel_switches(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """只改 chat_id 时不重设通道清单：`apply_channels` 不该被调用。"""

    applied: list[list[str]] = []
    monkeypatch.setattr("app.api.routes.settings.apply_channels", applied.append)
    client.patch("/api/settings", json={"notifications": {"channels": ["telegram"]}})

    response = client.patch(
        "/api/settings", json={"notifications": {"telegram": {"chat_id": "-100999"}}}
    )

    assert response.status_code == 200, response.text
    assert applied == [["telegram"]]
    assert response.json()["notifications"]["channels"] == ["telegram"]


def test_channel_credentials_are_reported_as_configured_but_never_echoed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC5：token 与签名密钥只来自环境变量，响应里只有两个布尔，没有明文。"""

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token-plain-value")
    monkeypatch.setenv("WEBHOOK_SIGNING_SECRET", "signing-secret-plain-value")
    get_settings.cache_clear()

    response = client.get("/api/settings")

    assert response.status_code == 200, response.text
    assert "bot-token-plain-value" not in response.text
    assert "signing-secret-plain-value" not in response.text
    notifications = response.json()["notifications"]
    assert notifications["telegram"]["token_configured"] is True
    assert notifications["webhook"]["secret_configured"] is True


def test_credentials_default_to_not_configured(client: TestClient) -> None:
    notifications = client.get("/api/settings").json()["notifications"]

    assert notifications["telegram"]["token_configured"] is False
    assert notifications["webhook"]["secret_configured"] is False


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
        {"data_sources": {"provider": "fake"}},
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
    succeeded = start_sync_job(OKX_PROVIDER, "candles")
    finish_sync_job(succeeded.id, "succeeded", rows=4)
    failed = start_sync_job(OKX_PROVIDER, "instruments")
    finish_sync_job(failed.id, "failed", error="OKX 超时")

    body = client.get("/api/settings").json()

    assert "provider" not in body["data_sources"]
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


# ---------------------------------------------------- 测试发送与最近投递


class _FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class _StubSink:
    """替身通道：记录收到的事件，按给定结果返回，不发任何请求。"""

    def __init__(self, result: DeliveryResult) -> None:
        self._result = result
        self.events: list[DomainEvent] = []

    def accepts(self, event: DomainEvent) -> bool:
        return event.kind == "alert"

    async def deliver(self, event: DomainEvent) -> DeliveryResult:
        self.events.append(event)
        return self._result


def _patch_channel(monkeypatch: pytest.MonkeyPatch, sink: _StubSink) -> dict[str, object]:
    """把「测试发送」构造通道的那一步换成本地替身，并记录它拿到的配置。"""

    seen: dict[str, object] = {}

    def build(name: str, *, config: object) -> _StubSink:
        seen["name"] = name
        seen["config"] = config
        return sink

    monkeypatch.setattr("app.api.routes.settings.build_channel", build)
    return seen


def test_test_send_uses_the_same_channel_config_and_records_delivery(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """测试发送走同一个通道构造入口，用的是当前设置与环境变量的合成配置。"""

    client.patch(
        "/api/settings",
        json={"notifications": {"telegram": {"chat_id": "-1001234567890"}}},
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token-plain-value")
    get_settings.cache_clear()
    sink = _StubSink(DeliveryResult("telegram", "delivered"))
    seen = _patch_channel(monkeypatch, sink)

    response = client.post("/api/settings/notifications/test", json={"channel": "telegram"})

    assert response.status_code == 200, response.text
    assert response.json() == {"channel": "telegram", "status": "delivered", "error": None}
    assert seen["name"] == "telegram"
    # 路由交给通道的是「投递时现读配置」的入口，不是一个已经读好的快照。
    provider = seen["config"]
    assert callable(provider)
    config = provider()
    assert config.telegram_chat_id == "-1001234567890"
    assert config.telegram_bot_token == "bot-token-plain-value"
    assert config.telegram_api_base == "https://api.telegram.org"
    assert "bot-token-plain-value" not in response.text

    event = sink.events[0]
    assert event.kind == "alert"
    assert event.payload["alert"]["title"] == "测试消息"

    rows = client.get("/api/settings/notifications/deliveries").json()["items"]
    assert [(row["channel"], row["status"], row["error"]) for row in rows] == [
        ("telegram", "delivered", None)
    ]


def test_test_send_reports_a_channel_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed = DeliveryResult("webhook", "failed", "HTTP 404（永久错误，不重试）")
    _patch_channel(monkeypatch, _StubSink(failed))

    response = client.post("/api/settings/notifications/test", json={"channel": "webhook"})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "channel": "webhook",
        "status": "failed",
        "error": "HTTP 404（永久错误，不重试）",
    }
    rows = client.get("/api/settings/notifications/deliveries").json()["items"]
    assert rows[0]["status"] == "failed"
    assert rows[0]["error"] == "HTTP 404（永久错误，不重试）"


def test_test_send_survives_a_channel_that_raises(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _RaisingSink(_StubSink):
        async def deliver(self, event: DomainEvent) -> DeliveryResult:
            raise RuntimeError("通道实现崩了")

    _patch_channel(monkeypatch, _RaisingSink(DeliveryResult("telegram", "delivered")))

    response = client.post("/api/settings/notifications/test", json={"channel": "telegram"})

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"
    assert response.json()["error"] == "通道实现崩了"


def test_test_send_only_accepts_external_channels(client: TestClient) -> None:
    """浏览器通道的权限只能由页面申请，服务端没有可测的东西。"""

    assert (
        client.post("/api/settings/notifications/test", json={"channel": "browser"}).status_code
        == 422
    )


def test_recent_deliveries_are_newest_first_and_respect_the_limit(client: TestClient) -> None:
    base = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    for index in range(3):
        asyncio.run(
            record_delivery(
                DeliveryResult("telegram", "delivered"),
                f"al_{index}",
                clock=_FixedClock(base + timedelta(minutes=index)),
            )
        )

    items = client.get("/api/settings/notifications/deliveries").json()["items"]

    assert [item["alert_id"] for item in items] == ["al_2", "al_1", "al_0"]
    assert items[0]["created_at"] == "2026-11-20T12:02:00Z"
    assert client.get("/api/settings/notifications/deliveries?limit=1").json()["items"] == [
        items[0]
    ]
    assert client.get("/api/settings/notifications/deliveries?limit=0").status_code == 422


@pytest.mark.parametrize("channel", ["telegram", "webhook"])
def test_test_send_walks_the_real_channel_wiring(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, channel: str
) -> None:
    """端到端：不打桩 `build_channel`，用 MockTransport 拦住真实通道发出的请求。

    这条盯的是「路由传什么 → `build_channel` 怎么装 → 通道怎么读配置」三段真实衔接：
    打桩那条用例只验证路由与替身之间的约定，装错一层在这里才会红。
    """

    client.patch(
        "/api/settings",
        json={
            "notifications": {
                "telegram": {"chat_id": "-1001234567890"},
                "webhook": {"url": "https://example.invalid/hooks/trading"},
            }
        },
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token-plain-value")
    get_settings.cache_clear()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    # 通道自己新建的 transport 换成拦请求的替身，其余装配全部走真实代码。
    monkeypatch.setattr(
        "app.events.sinks.http.httpx.AsyncHTTPTransport",
        lambda: httpx.MockTransport(handler),
    )

    response = client.post("/api/settings/notifications/test", json={"channel": channel})

    assert response.status_code == 200, response.text
    assert response.json() == {"channel": channel, "status": "delivered", "error": None}
    assert len(requests) == 1
    url = str(requests[0].url)
    body = json.loads(requests[0].content)
    if channel == "telegram":
        assert url == "https://api.telegram.org/botbot-token-plain-value/sendMessage"
        assert body["chat_id"] == "-1001234567890"
        assert body["text"].startswith("[info] 测试消息")
        assert body["disable_web_page_preview"] is True
    else:
        assert url == "https://example.invalid/hooks/trading"
        assert body["source"] == "trading"
        assert body["title"] == "测试消息"
    # 测试发送与通道开关无关：默认通道清单是 ["browser"]，照样能发出去。
    assert client.get("/api/settings").json()["notifications"]["channels"] == ["browser"]

    rows = client.get("/api/settings/notifications/deliveries").json()["items"]
    assert [(row["channel"], row["status"], row["error"]) for row in rows] == [
        (channel, "delivered", None)
    ]


def test_test_send_reports_a_missing_receiver_instead_of_a_crash(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """接收方为空时给可读提示，不把内部异常文本抛给页面。"""

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token-plain-value")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.events.sinks.http.httpx.AsyncHTTPTransport",
        lambda: httpx.MockTransport(lambda _request: httpx.Response(200, json={"ok": True})),
    )

    response = client.post("/api/settings/notifications/test", json={"channel": "telegram"})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "channel": "telegram",
        "status": "failed",
        "error": "未配置：请先在设置页填写 Telegram chat_id",
    }

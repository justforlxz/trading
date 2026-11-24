"""设置端点：五类设置、分组更新、密钥只写不读、通知通道与投递台账。"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.alerts import ALERT_TYPES
from app.config import get_settings
from app.db import session_scope
from app.events import DeliveryDigest, DeliveryResult, DomainEvent, record_delivery
from app.events.sinks.registry import SinkRegistry
from app.jobs import OKX_PROVIDER
from app.market import finish_sync_job, start_sync_job
from tests.api.conftest import seed_instruments
from tests.factories.instruments import make_ref

UTC_ZULU = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

DEFAULT_DISPLAY = {
    "color_scheme": "system",
    "default_bar": "1d",
    "price_precision": 2,
    "home_layout": "cockpit",
    "homepage_pinned": [],
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
        "macro": {
            "series": {
                "us10y": {"minute": "yahoo", "daily": "treasury"},
                "us2y": {"minute": None, "daily": "treasury"},
                "vix": {"minute": "yahoo", "daily": "cboe"},
            },
            "scheduler": {"minute": "1m"},
        },
        "equity": {
            "provider": "yahoo",
            "symbols": ["SPY", "QQQ"],
            "scheduler": {"minute": "1m"},
        },
    }
    assert body["notifications"] == {
        **DEFAULT_NOTIFICATIONS,
        "subscriptions": {
            "browser": {"types": list(ALERT_TYPES), "min_severity": "info"},
            "telegram": {"types": ["risk", "strategy"], "min_severity": "warning"},
            "webhook": {"types": [], "min_severity": "warning"},
        },
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
    """替身通道：记录收到的投递内容，按给定结果返回，不发任何请求。"""

    def __init__(self, result: DeliveryResult) -> None:
        self._result = result
        self.digests: list[DeliveryDigest] = []

    async def deliver(self, digest: DeliveryDigest) -> DeliveryResult:
        self.digests.append(digest)
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

    digest = sink.digests[0]
    assert digest.total == 1
    assert digest.items[0].alert["title"] == "测试消息"

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
        assert body["text"].startswith("🔔 系统 · 提示")
        assert "来自设置页的测试发送" in body["text"]
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


def test_macro_provider_name_must_be_registered(client: TestClient) -> None:
    """未登记的名字在契约层被拒，不写进设置文档。"""

    response = client.patch(
        "/api/settings",
        json={"data_sources": {"macro": {"series": {"vix": {"minute": "nope"}}}}},
    )

    assert response.status_code == 422


def test_macro_provider_must_be_allowed_for_that_series(client: TestClient) -> None:
    """已登记但不适用于该序列的 provider 返回 400，并列出可选值。"""

    response = client.patch(
        "/api/settings",
        json={"data_sources": {"macro": {"series": {"vix": {"minute": "treasury"}}}}},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "cboe" in detail and "yahoo" in detail


def test_macro_provider_switch_persists_and_reads_back(client: TestClient) -> None:
    response = client.patch(
        "/api/settings",
        json={"data_sources": {"macro": {"series": {"vix": {"minute": "cboe"}}}}},
    )

    assert response.status_code == 200, response.text
    macro = response.json()["data_sources"]["macro"]
    assert macro["series"]["vix"]["minute"] == "cboe"
    # 其它序列不被顺手覆盖
    assert macro["series"]["us10y"]["daily"] == "treasury"


def test_macro_daily_slot_rejects_a_minute_only_provider(client: TestClient) -> None:
    """日结槽填分钟级源：写入时就 400，不让「分钟级 10Y 减日线 2Y」的配置进库。"""

    response = client.patch(
        "/api/settings",
        json={"data_sources": {"macro": {"series": {"us10y": {"daily": "yahoo"}}}}},
    )

    assert response.status_code == 400
    assert "treasury" in response.json()["detail"]


def test_macro_minute_slot_rejects_a_settlement_provider(client: TestClient) -> None:
    response = client.patch(
        "/api/settings",
        json={"data_sources": {"macro": {"series": {"us10y": {"minute": "treasury"}}}}},
    )

    assert response.status_code == 400
    assert "yahoo" in response.json()["detail"]


def test_macro_scheduler_interval_is_restricted(client: TestClient) -> None:
    response = client.patch(
        "/api/settings", json={"data_sources": {"macro": {"scheduler": {"minute": "1h"}}}}
    )

    assert response.status_code == 422


def test_equity_provider_switch_persists_and_reads_back(client: TestClient) -> None:
    """AC1 的配置侧：改 `equity.provider` 就换实现，其它子项保持原值。"""

    response = client.patch(
        "/api/settings", json={"data_sources": {"equity": {"provider": "stooq"}}}
    )

    assert response.status_code == 200, response.text
    equity = response.json()["data_sources"]["equity"]
    assert equity["provider"] == "stooq"
    # 未提交的标的清单与调度周期保持原值，不被顺手覆盖成空。
    assert equity["symbols"] == ["SPY", "QQQ"]
    assert equity["scheduler"] == {"minute": "1m"}

    again = client.get("/api/settings").json()["data_sources"]["equity"]
    assert again["provider"] == "stooq"


def test_equity_provider_name_must_be_registered(client: TestClient) -> None:
    response = client.patch(
        "/api/settings", json={"data_sources": {"equity": {"provider": "polygon"}}}
    )

    assert response.status_code == 422


def test_equity_symbols_replace_the_whole_list(client: TestClient) -> None:
    response = client.patch(
        "/api/settings", json={"data_sources": {"equity": {"symbols": ["SPY"]}}}
    )

    assert response.status_code == 200, response.text
    assert response.json()["data_sources"]["equity"]["symbols"] == ["SPY"]


def test_equity_symbols_must_not_be_empty(client: TestClient) -> None:
    response = client.patch("/api/settings", json={"data_sources": {"equity": {"symbols": []}}})

    assert response.status_code == 400
    assert "不能为空" in response.json()["detail"]


def test_equity_symbols_reject_whitespace(client: TestClient) -> None:
    response = client.patch(
        "/api/settings", json={"data_sources": {"equity": {"symbols": ["SP Y"]}}}
    )

    assert response.status_code == 400
    assert "空白" in response.json()["detail"]


def test_equity_scheduler_interval_is_restricted(client: TestClient) -> None:
    response = client.patch(
        "/api/settings", json={"data_sources": {"equity": {"scheduler": {"minute": "1h"}}}}
    )

    assert response.status_code == 422


# ------------------------------------------------- 按通道的类型订阅（AC2/AC3/AC6）


class _RecordingSink:
    """只记录投递内容的通道替身，名字与真实通道一致，便于按名字套订阅。"""

    name = "telegram"

    def __init__(self) -> None:
        self.digests: list[DeliveryDigest] = []

    async def deliver(self, digest: DeliveryDigest) -> DeliveryResult:
        self.digests.append(digest)
        return DeliveryResult(channel=self.name, status="delivered")


class _MemoryRecorder:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str | None]] = []

    async def __call__(self, result: DeliveryResult, alert_id: str | None) -> None:
        self.rows.append((result.channel, alert_id))


def _alert_event(
    *,
    alert_id: str = "al_1",
    type_: str = "indicator",
    severity: str = "info",
    minutes: int = 0,
) -> DomainEvent:
    from app.events import DomainEvent

    return DomainEvent(
        kind="alert",
        inst_id="XAAPL-USDT",
        payload={
            "rule_id": "candle1h.ma20_cross",
            "alert": {
                "id": alert_id,
                "type": type_,
                "severity": severity,
                "title": "收盘价跌破 MA20",
                "detail": "XAAPL-USDT 收盘价 101 跌破 MA20（102）",
                "instrument_id": "XAAPL-USDT",
            },
        },
        occurred_at=datetime(2026, 11, 20, 12, 0, tzinfo=UTC) + timedelta(minutes=minutes),
    )


def _settings_bound_registry(sink: _RecordingSink) -> SinkRegistry:
    """与装配根同一种接法：每次投递现读设置文档里的订阅。"""

    from app.settings import load_settings

    return SinkRegistry(
        [sink],
        enabled=["telegram"],
        recorder=_MemoryRecorder(),
        subscriptions=lambda: load_settings().notifications.get("subscriptions", {}),
    )


def test_default_subscriptions_are_reported_for_every_channel(client: TestClient) -> None:
    """未配置时返回默认订阅，页面显示的就是生效值。"""

    body = client.get("/api/settings").json()["notifications"]["subscriptions"]

    assert body["telegram"] == {"types": ["risk", "strategy"], "min_severity": "warning"}
    assert body["browser"] == {"types": list(ALERT_TYPES), "min_severity": "info"}
    assert body["webhook"] == {"types": [], "min_severity": "warning"}


def test_subscriptions_are_editable_and_persist(client: TestClient) -> None:
    """AC6：设置页整组提交订阅，保存后读回的是保存值。"""

    subscriptions = {
        "browser": {"types": ["risk", "data"], "min_severity": "warning"},
        "telegram": {"types": ["risk"], "min_severity": "critical"},
        "webhook": {"types": ["strategy"], "min_severity": "info"},
    }

    response = client.patch(
        "/api/settings", json={"notifications": {"subscriptions": subscriptions}}
    )

    assert response.status_code == 200, response.text
    assert response.json()["notifications"]["subscriptions"] == subscriptions
    assert client.get("/api/settings").json()["notifications"]["subscriptions"] == subscriptions


def test_unknown_alert_type_in_subscriptions_is_rejected(client: TestClient) -> None:
    response = client.patch(
        "/api/settings",
        json={"notifications": {"subscriptions": {"telegram": {"types": ["bracket"]}}}},
    )

    assert response.status_code == 422
    assert "未知提醒类型" in response.text


def test_editing_a_receiver_keeps_the_subscriptions(client: TestClient) -> None:
    """只改 chat_id 时订阅保持原值：两个子项各自合并。"""

    subscriptions = {
        "browser": {"types": [], "min_severity": "info"},
        "telegram": {"types": ["risk"], "min_severity": "info"},
        "webhook": {"types": [], "min_severity": "warning"},
    }
    client.patch("/api/settings", json={"notifications": {"subscriptions": subscriptions}})

    response = client.patch(
        "/api/settings", json={"notifications": {"telegram": {"chat_id": "-100999"}}}
    )

    assert response.status_code == 200, response.text
    body = response.json()["notifications"]
    assert body["subscriptions"] == subscriptions
    assert body["telegram"]["chat_id"] == "-100999"


def test_saved_subscriptions_drive_the_next_delivery(client: TestClient) -> None:
    """AC2/AC3/AC6：默认订阅挡下提示级技术形态，改完订阅后下一次评估就投递。

    投递侧与装配根一样「每次现读设置文档」，所以这里不需要重启、也不需要重新装配。
    """

    sink = _RecordingSink()
    registry = _settings_bound_registry(sink)

    async def scenario() -> None:
        # 默认订阅：Telegram 只收 risk + strategy 且 warning 以上
        await registry.deliver_round([_alert_event(alert_id="al_1")])
        assert sink.digests == []
        # 保存新订阅：telegram 收 indicator 且 info 以上
        client.patch(
            "/api/settings",
            json={
                "notifications": {
                    "subscriptions": {
                        "browser": {"types": list(ALERT_TYPES), "min_severity": "info"},
                        "telegram": {"types": ["indicator"], "min_severity": "info"},
                        "webhook": {"types": [], "min_severity": "warning"},
                    }
                }
            },
        )
        await registry.deliver_round([_alert_event(alert_id="al_2", minutes=11)])

    asyncio.run(scenario())

    assert len(sink.digests) == 1
    assert sink.digests[0].items[0].alert["id"] == "al_2"


def test_submitting_one_channel_keeps_the_other_subscriptions(client: TestClient) -> None:
    """只提交一个通道时，其余通道的订阅与门槛保持库中原值。"""

    client.patch(
        "/api/settings",
        json={
            "notifications": {
                "subscriptions": {
                    "browser": {"types": ["data"], "min_severity": "warning"},
                    "webhook": {"types": ["strategy"], "min_severity": "critical"},
                }
            }
        },
    )

    response = client.patch(
        "/api/settings",
        json={"notifications": {"subscriptions": {"telegram": {"types": ["risk"]}}}},
    )

    assert response.status_code == 200, response.text
    subscriptions = response.json()["notifications"]["subscriptions"]
    assert subscriptions["browser"] == {"types": ["data"], "min_severity": "warning"}
    assert subscriptions["webhook"] == {"types": ["strategy"], "min_severity": "critical"}
    # 没提交 min_severity 时沿用已存值；从未存过则回落到该通道的默认门槛，不是 info。
    assert subscriptions["telegram"] == {"types": ["risk"], "min_severity": "warning"}


def test_submitting_only_min_severity_keeps_the_types(client: TestClient) -> None:
    """只改最低严重度时，该通道已保存的类型清单不能被清空。"""

    client.patch(
        "/api/settings",
        json={"notifications": {"subscriptions": {"telegram": {"types": ["risk", "data"]}}}},
    )

    response = client.patch(
        "/api/settings",
        json={"notifications": {"subscriptions": {"telegram": {"min_severity": "critical"}}}},
    )

    assert response.status_code == 200, response.text
    assert response.json()["notifications"]["subscriptions"]["telegram"] == {
        "types": ["risk", "data"],
        "min_severity": "critical",
    }


def test_empty_subscription_update_is_rejected(client: TestClient) -> None:
    """空对象没有可写字段：当场 400，而不是静默地把整块订阅写成默认值。"""

    assert (
        client.patch("/api/settings", json={"notifications": {"subscriptions": {}}}).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/settings", json={"notifications": {"subscriptions": {"telegram": {}}}}
        ).status_code
        == 422
    )


# ---------------------------------------------------------------- 首页置顶（MKACG-965）


def _seed_watchlist(client: TestClient, count: int) -> list[str]:
    """同步 `count` 个标的并逐个加入自选；返回加入顺序的 inst_id。"""

    refs = [
        make_ref(inst_id=f"XPIN{index}-USDT", base_ccy=f"XPIN{index}") for index in range(count)
    ]
    seed_instruments(*refs)
    ids: list[str] = []
    for ref in refs:
        added = client.post("/api/watchlist", json={"inst_id": ref.inst_id})
        assert added.status_code == 201, added.text
        ids.append(ref.inst_id)
    return ids


def _display_in_db() -> dict[str, object]:
    """直接读 `settings.display` 列：验证失败时库里必须保持原值。"""

    with session_scope() as session:
        raw = session.execute(text("select display from settings where id = 1")).scalar_one()
    return json.loads(raw)


def test_homepage_pinned_is_empty_by_default_and_writable(client: TestClient) -> None:
    """默认没有置顶项；提交后按选择顺序落库，并能读回。"""

    pinned = _seed_watchlist(client, 3)
    assert client.get("/api/settings").json()["display"]["homepage_pinned"] == []

    selection = [pinned[2], pinned[0]]
    response = client.patch("/api/settings", json={"display": {"homepage_pinned": selection}})

    assert response.status_code == 200, response.text
    assert response.json()["display"]["homepage_pinned"] == selection
    assert client.get("/api/settings").json()["display"]["homepage_pinned"] == selection
    assert _display_in_db()["homepage_pinned"] == selection


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(["A", "B", "C", "D", "E", "F"], id="超过五个"),
        pytest.param(["A", "A"], id="重复元素"),
        pytest.param(["NOT-IN-WATCHLIST"], id="不在自选里"),
        pytest.param("XAAPL-USDT", id="非数组"),
        pytest.param(3, id="非数组整数"),
        pytest.param([1, 2], id="元素非字符串"),
        pytest.param([""], id="空字符串"),
    ],
)
def test_homepage_pinned_rejects_illegal_values_without_writing(
    client: TestClient, value: object
) -> None:
    """非法提交一律 400，且库里 `display` 一个字节都不变。"""

    ids = _seed_watchlist(client, 6)
    saved = [ids[0], ids[1]]
    assert (
        client.patch("/api/settings", json={"display": {"homepage_pinned": saved}}).status_code
        == 200
    )
    before = _display_in_db()

    # 用真实的自选标的顶替占位名，确保输在规则上而不是「不知道这个标的」。
    placeholders = dict(zip("ABCDEF", ids, strict=False))
    payload = (
        value if not isinstance(value, list) else [placeholders.get(item, item) for item in value]
    )
    response = client.patch("/api/settings", json={"display": {"homepage_pinned": payload}})

    assert response.status_code == 400, response.text
    assert _display_in_db() == before
    assert client.get("/api/settings").json()["display"]["homepage_pinned"] == saved


def test_patching_only_pinned_keeps_the_rest_of_the_display_group(client: TestClient) -> None:
    """只提交置顶项时，显示偏好的其它字段保持原值，不被默认值冲掉。"""

    ids = _seed_watchlist(client, 2)
    client.patch(
        "/api/settings",
        json={"display": {"color_scheme": "dark", "default_bar": "4h", "price_precision": 4}},
    )

    response = client.patch("/api/settings", json={"display": {"homepage_pinned": [ids[1]]}})

    assert response.status_code == 200, response.text
    display = response.json()["display"]
    assert display["homepage_pinned"] == [ids[1]]
    assert display["color_scheme"] == "dark"
    assert display["default_bar"] == "4h"
    assert display["price_precision"] == 4


def test_pinned_item_removed_from_watchlist_stays_in_settings(client: TestClient) -> None:
    """读取侧只求交集，不改写库：从自选删掉的置顶项仍留在设置文档里。"""

    ids = _seed_watchlist(client, 3)
    assert (
        client.patch("/api/settings", json={"display": {"homepage_pinned": ids}}).status_code == 200
    )

    removed = client.delete(f"/api/watchlist/{ids[1]}")
    assert removed.status_code in (200, 204), removed.text

    assert client.get("/api/settings").json()["display"]["homepage_pinned"] == ids
    assert _display_in_db()["homepage_pinned"] == ids


def test_pinned_items_removed_from_watchlist_survive_a_save(client: TestClient) -> None:
    """弹窗只提交看得见的选择：已不在自选的置顶项由服务端补回，不能被一次保存删掉。"""

    ids = _seed_watchlist(client, 3)
    saved = client.patch("/api/settings", json={"display": {"homepage_pinned": ids}})
    assert saved.status_code == 200, saved.text
    assert client.delete(f"/api/watchlist/{ids[2]}").status_code == 204

    # 弹窗里只剩两个候选，保存时提交的也只有这两个。
    again = client.patch("/api/settings", json={"display": {"homepage_pinned": ids[:2]}})

    assert again.status_code == 200, again.text
    assert again.json()["display"]["homepage_pinned"] == ids
    assert client.get("/api/settings").json()["display"]["homepage_pinned"] == ids
    assert _display_in_db()["homepage_pinned"] == ids

    # 换顺序再存一次：看不见的那项留在原来的位置，看得见的按提交顺序。
    reordered = client.patch(
        "/api/settings", json={"display": {"homepage_pinned": [ids[1], ids[0]]}}
    )

    assert reordered.status_code == 200, reordered.text
    assert reordered.json()["display"]["homepage_pinned"] == [ids[1], ids[0], ids[2]]

    # 加回自选后恢复显示：数组原样还在，顺序就是数组里的顺序。
    assert client.post("/api/watchlist", json={"inst_id": ids[2]}).status_code == 201
    assert client.get("/api/settings").json()["display"]["homepage_pinned"] == [
        ids[1],
        ids[0],
        ids[2],
    ]


def test_pinned_save_counts_hidden_items_against_the_limit(client: TestClient) -> None:
    """已不在自选的置顶项仍占名额：再加到超过 5 个要当场 400，且不落库。"""

    ids = _seed_watchlist(client, 6)
    assert (
        client.patch("/api/settings", json={"display": {"homepage_pinned": ids[:3]}}).status_code
        == 200
    )
    assert client.delete(f"/api/watchlist/{ids[0]}").status_code == 204
    before = _display_in_db()

    too_many = client.patch("/api/settings", json={"display": {"homepage_pinned": ids[1:]}})

    assert too_many.status_code == 400, too_many.text
    assert "另有 1 个已不在自选的置顶项会保留" in too_many.json()["detail"]
    assert _display_in_db() == before

    fits = client.patch("/api/settings", json={"display": {"homepage_pinned": ids[1:5]}})

    assert fits.status_code == 200, fits.text
    assert fits.json()["display"]["homepage_pinned"] == [ids[0], *ids[1:5]]

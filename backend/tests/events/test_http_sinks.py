"""Telegram 与 Webhook 两个外部通道：请求形状、错误分类、有界重试与通道隔离。

用例一律用 `httpx.MockTransport` 拦请求，**不做真实投递**：本仓库没有真实 bot token，
也不该在测试里往聊天窗口发消息。断言的是「发出去的东西长什么样」与「台账记了什么」。

退避时长由注入的假 `sleep` 记录下来，不真的等待，因此 3 次退避的断言是毫秒级完成。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.events import DeliveryDigest, DomainEvent, digest_of
from app.events.sinks.base import DeliveryResult
from app.events.sinks.config import ChannelConfig
from app.events.sinks.http import RETRY_DELAYS
from app.events.sinks.registry import CHANNEL_BUILDERS, SinkDeps, SinkRegistry
from app.events.sinks.telegram import TelegramSink
from app.events.sinks.webhook import SIGNATURE_HEADER, WebhookSink

TOKEN = "123456789:test-bot-token-not-a-real-credential"
CHAT_ID = "-1001234567890"
SECRET = "signing-secret-not-a-real-credential"
URL = "https://example.invalid/hooks/trading"
TELEGRAM_API = "https://api.telegram.org"
MOMENT = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)

ALERT: dict[str, Any] = {
    "id": "al_XAAPL-USDT_20261120120000000000",
    "type": "price",
    "severity": "warning",
    "title": "价格偏离参考价",
    "detail": "XAAPL-USDT 最新成交价 101.5 高于 指数价 100，偏离 1.5%",
    "instrument_id": "XAAPL-USDT",
    "triggered_at": "2026-11-20T12:00:00Z",
}


class Sleeps:
    """记录退避时长，不真的等：测试要的是「等了多久」，不是「真的等了」。"""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class MemoryRecorder:
    """投递台账的内存替身：与 `SinkRegistry` 的记录器形状一致。"""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str | None]] = []

    async def __call__(self, result: DeliveryResult, alert_id: str | None) -> None:
        self.rows.append((result.channel, result.status, result.error))


class BrokenTelegram(TelegramSink):
    """投递时直接抛错的 Telegram 通道：用来验证通道之间互不影响。"""

    async def deliver(self, digest: DeliveryDigest) -> DeliveryResult:
        raise RuntimeError("Telegram 上游不可用")


def _event_at(offset_minutes: int = 0) -> DomainEvent:
    """一条告警事件，时刻从 `MOMENT` 起按分钟偏移。"""

    return DomainEvent(
        kind="alert",
        inst_id="XAAPL-USDT",
        payload={"rule_id": "price_deviation", "alert": dict(ALERT)},
        occurred_at=MOMENT + timedelta(minutes=offset_minutes),
    )


def _digest_at(offset_minutes: int = 0) -> DeliveryDigest:
    """一次投递的内容：单条告警，时刻与 `_event_at` 一致。"""

    digest = digest_of(_event_at(offset_minutes))
    assert digest is not None
    return digest


def _digest() -> DeliveryDigest:
    return _digest_at()


def _source(**overrides: str):
    """通道的配置读取入口：与装配根一致，是一个「每次投递现读」的普通可调用对象。"""

    config = _config(**overrides)

    def provider() -> ChannelConfig:
        return config

    return provider


def _config(**overrides: str) -> ChannelConfig:
    values = {
        "telegram_chat_id": CHAT_ID,
        "telegram_bot_token": TOKEN,
        "telegram_api_base": TELEGRAM_API,
        "webhook_url": URL,
        "webhook_signing_secret": SECRET,
    }
    values.update(overrides)
    return ChannelConfig(**values)


def _allow_everything() -> dict[str, Any]:
    """这几个用例只关心通道隔离与台账，订阅就不在这里验证了：全开。"""

    return {
        "browser": {"types": ["price"], "min_severity": "info"},
        "telegram": {"types": ["price"], "min_severity": "info"},
        "webhook": {"types": ["price"], "min_severity": "info"},
    }


def _responding(status: int, *, payload: Any = None, headers: Any = None) -> Any:
    """固定响应的 handler；返回 `(handler, 收到的请求列表)`。"""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, json=payload, headers=headers)

    return handler, requests


def _sequence(responses: list[httpx.Response | Exception]) -> Any:
    """按顺序返回响应（或抛异常）的 handler；用尽后重复最后一个。"""

    requests: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    return handler, requests


# ------------------------------------------------------------------ Telegram


def test_telegram_sends_the_documented_request() -> None:
    """AC1（MockTransport，未做真实投递）：地址、chat_id、模板正文与关闭预览。"""

    handler, requests = _responding(200, payload={"ok": True})
    sink = TelegramSink(_source(), transport=httpx.MockTransport(handler))

    result = asyncio.run(sink.deliver(_digest()))

    assert result == DeliveryResult("telegram", "delivered")
    assert len(requests) == 1
    assert str(requests[0].url) == f"{TELEGRAM_API}/bot{TOKEN}/sendMessage"
    assert requests[0].method == "POST"
    body = json.loads(requests[0].content)
    assert body == {
        "chat_id": CHAT_ID,
        "text": (
            "⚠️ 价格区间 · 警告\n"
            "XAAPL-USDT 最新成交价 101.5 高于 指数价 100，偏离 1.5%\n"
            "2026-11-20T12:00:00Z"
        ),
        "disable_web_page_preview": True,
    }


def test_telegram_401_is_permanent_and_never_leaks_the_token() -> None:
    """AC2：401 不重试，失败原因可读，且不含 token 原文。"""

    handler, requests = _responding(401, payload={"ok": False})
    sleeps = Sleeps()
    sink = TelegramSink(_source(), transport=httpx.MockTransport(handler), sleep=sleeps)

    result = asyncio.run(sink.deliver(_digest()))

    assert result.status == "failed"
    assert len(requests) == 1
    assert sleeps.calls == []
    assert result.error == "HTTP 401（永久错误，不重试）"
    assert TOKEN not in str(result.error)


def test_a_delivery_writes_no_log_line_with_the_token(caplog: pytest.LogCaptureFixture) -> None:
    """安全：投递不写访问日志，日志里不出现 token 原文。

    这条盯的是日志而不是 `DeliveryResult.error`：`httpx.Client` 在 INFO 级别会打印
    `HTTP Request: POST <完整地址>`，而 Telegram 的令牌就在地址路径里。断言两条——
    投递过程没有产生 httpx 的访问日志，且整段日志里没有令牌。
    """

    caplog.set_level(logging.DEBUG)
    handler, _ = _responding(200, payload={"ok": True})
    sink = TelegramSink(_source(), transport=httpx.MockTransport(handler))

    result = asyncio.run(sink.deliver(_digest()))

    assert result.status == "delivered"
    assert "HTTP Request" not in caplog.text
    assert TOKEN not in caplog.text


def test_a_failing_delivery_writes_no_log_line_with_the_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """失败路径同样不能泄漏：401 与 5xx 都不会把地址写进日志。"""

    caplog.set_level(logging.DEBUG)
    handler, _ = _responding(503)
    sink = TelegramSink(_source(), transport=httpx.MockTransport(handler), sleep=Sleeps())

    asyncio.run(sink.deliver(_digest()))

    assert "HTTP Request" not in caplog.text
    assert TOKEN not in caplog.text


def test_telegram_429_waits_for_the_upstream_retry_after() -> None:
    """AC2：429 带 `retry_after` 时按它等待，随后成功。"""

    handler, requests = _sequence(
        [
            httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 5}}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    sleeps = Sleeps()
    sink = TelegramSink(_source(), transport=httpx.MockTransport(handler), sleep=sleeps)

    result = asyncio.run(sink.deliver(_digest()))

    assert result.status == "delivered"
    assert len(requests) == 2
    assert sleeps.calls == [5.0]


def test_telegram_5xx_retries_the_whole_ladder_and_stops() -> None:
    """AC2：5xx 按 2s / 8s / 30s 退避，用尽上限即返回失败，不再继续。"""

    handler, requests = _responding(503)
    sleeps = Sleeps()
    sink = TelegramSink(_source(), transport=httpx.MockTransport(handler), sleep=sleeps)

    result = asyncio.run(sink.deliver(_digest()))

    assert result.status == "failed"
    assert len(requests) == len(RETRY_DELAYS) + 1 == 4
    assert sleeps.calls == [2.0, 8.0, 30.0]
    assert result.error == "HTTP 503，已尝试 4 次"
    assert TOKEN not in str(result.error)


def test_telegram_timeout_is_retried_and_reported_readably() -> None:
    """AC2：超时算可恢复错误，重试到上限后给出可读原因。"""

    handler, requests = _sequence([httpx.ReadTimeout("timed out")])
    sleeps = Sleeps()
    sink = TelegramSink(_source(), transport=httpx.MockTransport(handler), sleep=sleeps)

    result = asyncio.run(sink.deliver(_digest()))

    assert result.status == "failed"
    assert len(requests) == 4
    assert sleeps.calls == [2.0, 8.0, 30.0]
    assert result.error == "请求超时（10 秒），已尝试 4 次"


class _HangingBody(httpx.AsyncByteStream):
    """先回响应头、body 永远吐不完的上游：只包住「拿到响应头」的写法会在这里挂住。"""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        await asyncio.sleep(3600)
        yield b""  # pragma: no cover - 超时先到，这一行走不到


def test_a_response_body_that_never_ends_hits_the_same_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超时窗口覆盖「发请求 + 读响应体」：上游只回响应头也必须按时放弃。"""

    monkeypatch.setattr("app.events.sinks.http.TIMEOUT_SECONDS", 0.05)
    sink = TelegramSink(
        _source(),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=_HangingBody())),
        sleep=Sleeps(),
    )

    async def scenario() -> DeliveryResult:
        # 外层再套一层上限：万一 body 读取没有被超时窗口包住，用例是失败而不是挂住。
        return await asyncio.wait_for(sink.deliver(_digest()), timeout=10.0)

    started = time.monotonic()
    result = asyncio.run(scenario())
    elapsed = time.monotonic() - started

    assert result.status == "failed"
    assert result.error == "请求超时（0.05 秒），已尝试 4 次"
    assert elapsed < 5.0, "body 读取没有被超时窗口包住"


def test_telegram_without_credentials_reports_unconfigured_without_a_request() -> None:
    """缺 token 或 chat_id 都不发请求，且逐项说明缺什么、该去哪配。"""

    handler, requests = _responding(200, payload={"ok": True})

    no_token = TelegramSink(
        _source(telegram_bot_token=""),
        transport=httpx.MockTransport(handler),
    )
    no_chat = TelegramSink(
        _source(telegram_chat_id=""),
        transport=httpx.MockTransport(handler),
    )

    tokenless = asyncio.run(no_token.deliver(_digest()))
    chatless = asyncio.run(no_chat.deliver(_digest()))

    assert requests == []
    assert tokenless.status == "failed"
    assert tokenless.error == "未配置：需要注入 TELEGRAM_BOT_TOKEN 环境变量"
    assert chatless.status == "failed"
    assert chatless.error == "未配置：请先在设置页填写 Telegram chat_id"


# ------------------------------------------------------------------- Webhook


def test_webhook_signs_the_exact_body_it_sends() -> None:
    """AC3（MockTransport，未做真实投递）：原始字节验签通过，八个字段齐全。"""

    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        expected = hmac.new(SECRET.encode(), request.content, hashlib.sha256).hexdigest()
        assert request.headers[SIGNATURE_HEADER] == f"sha256={expected}"
        assert request.headers["content-type"] == "application/json"
        return httpx.Response(204)

    sink = WebhookSink(_source(), transport=httpx.MockTransport(handler))

    result = asyncio.run(sink.deliver(_digest()))

    assert result == DeliveryResult("webhook", "delivered")
    body = json.loads(received[0].content)
    assert body == {
        "source": "trading",
        "id": ALERT["id"],
        "type": "price",
        "severity": "warning",
        "title": ALERT["title"],
        "detail": ALERT["detail"],
        "instrument_id": "XAAPL-USDT",
        "message": (
            "⚠️ 价格区间 · 警告\n"
            "XAAPL-USDT 最新成交价 101.5 高于 指数价 100，偏离 1.5%\n"
            "2026-11-20T12:00:00Z"
        ),
        "occurred_at": "2026-11-20T12:00:00Z",
    }
    assert set(("id", "type", "severity", "title", "detail", "instrument_id")) <= set(body)


def test_webhook_without_a_secret_sends_the_body_unsigned() -> None:
    handler, requests = _responding(200)
    sink = WebhookSink(
        _source(webhook_signing_secret=""),
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(sink.deliver(_digest()))

    assert result.status == "delivered"
    assert SIGNATURE_HEADER not in requests[0].headers


def test_webhook_client_error_is_not_retried() -> None:
    """4xx（408 / 429 之外）是永久错误：地址写错不该反复轰炸对方。"""

    handler, requests = _responding(404)
    sleeps = Sleeps()
    sink = WebhookSink(_source(), transport=httpx.MockTransport(handler), sleep=sleeps)

    result = asyncio.run(sink.deliver(_digest()))

    assert result.status == "failed"
    assert len(requests) == 1
    assert sleeps.calls == []
    assert result.error == "HTTP 404（永久错误，不重试）"


def test_webhook_without_a_url_reports_unconfigured_without_a_request() -> None:
    handler, requests = _responding(200)
    sink = WebhookSink(_source(webhook_url=""), transport=httpx.MockTransport(handler))

    result = asyncio.run(sink.deliver(_digest()))

    assert result.status == "failed"
    assert requests == []
    assert result.error == "未配置：请先在设置页填写 Webhook 接收地址"


# --------------------------------------------------------------- 通道隔离


def test_one_channel_failing_does_not_stop_the_other() -> None:
    """AC7：Telegram 抛错时 Webhook 仍然投递成功，两条台账都在。"""

    handler, _ = _responding(200)
    recorder = MemoryRecorder()
    registry = SinkRegistry(
        [
            BrokenTelegram(_source()),
            WebhookSink(_source(), transport=httpx.MockTransport(handler)),
        ],
        recorder=recorder,
        subscriptions=_allow_everything,
    )

    results = asyncio.run(registry.deliver(_event_at()))

    assert [(item.channel, item.status) for item in results] == [
        ("telegram", "failed"),
        ("webhook", "delivered"),
    ]
    assert [(row[0], row[1]) for row in recorder.rows] == [
        ("telegram", "failed"),
        ("webhook", "delivered"),
    ]
    assert recorder.rows[0][2] == "Telegram 上游不可用"


def test_telegram_delivery_is_recorded_as_delivered() -> None:
    """AC1：投递成功后注册表写一行 `delivered` 台账（未做真实投递）。"""

    handler, requests = _responding(200, payload={"ok": True})
    recorder = MemoryRecorder()
    registry = SinkRegistry(
        [TelegramSink(_source(), transport=httpx.MockTransport(handler))],
        enabled=["telegram"],
        recorder=recorder,
        subscriptions=_allow_everything,
    )

    asyncio.run(registry.deliver(_event_at()))

    assert len(requests) == 1
    assert recorder.rows == [("telegram", "delivered", None)]


def test_each_enabled_channel_writes_its_own_delivery_row() -> None:
    """MUST：每个通道每次投递各写一行台账；没开的外部通道不产生记录。"""

    handler, requests = _responding(200)
    recorder = MemoryRecorder()
    registry = SinkRegistry(
        [WebhookSink(_source(), transport=httpx.MockTransport(handler))],
        enabled=["browser", "webhook"],
        recorder=recorder,
        subscriptions=_allow_everything,
    )

    asyncio.run(registry.deliver(_event_at()))

    assert len(requests) == 1
    assert recorder.rows == [("webhook", "delivered", None)]


def test_turning_a_channel_off_at_runtime_stops_new_ledger_rows() -> None:
    """AC4：关掉通道后不再产生新台账；打开后立即恢复，不用重启进程。"""

    handler, requests = _responding(200)
    recorder = MemoryRecorder()
    registry = SinkRegistry(
        [WebhookSink(_source(), transport=httpx.MockTransport(handler))],
        enabled=["webhook"],
        recorder=recorder,
        subscriptions=_allow_everything,
    )

    asyncio.run(registry.deliver(_event_at()))
    registry.set_channels([])
    asyncio.run(registry.deliver(_event_at(11)))
    registry.set_channels(["webhook"])
    asyncio.run(registry.deliver(_event_at(22)))

    assert len(requests) == 2
    assert recorder.rows == [
        ("webhook", "delivered", None),
        ("webhook", "delivered", None),
    ]


def test_channels_are_built_from_the_registry_table() -> None:
    """注册表里三行：新通道只加实现 + 一行登记，构造后都在注册表里。"""

    deps = SinkDeps(broadcast=lambda *_args, **_kwargs: None, config=_source())

    built = {name: builder(deps).name for name, builder in CHANNEL_BUILDERS.items()}

    assert built == {"browser": "browser", "telegram": "telegram", "webhook": "webhook"}

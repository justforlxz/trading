"""WebSocket 私有频道：按 `ts` + `price` 去重、断线重连、重连不发单。

判据取自 MKACG-729：断线 3 次后重连成功，消息按 `ts` + `price` 去重后无重复；
重连过程中不产生重复订单。

重连不产生订单这件事**不用靠调用方记得**：本类手上没有交易端口，每次重连只发
`login` 与 `subscribe` 两帧。用例直接断言「每条连接上只发过这两帧」。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from app.config import OKX_WS_PRIVATE_URL_DEMO, OKX_WS_PRIVATE_URL_PROD, Settings
from app.core import ValidationError
from app.exchange import ExchangeError
from app.exchange.okx.ws import DEFAULT_CHANNELS, Deduper, OkxWebSocket, message_key
from tests.fakes.okx.trade import FakeCredentials

CREDENTIALS = FakeCredentials()


class FakeSocket:
    """假的已连接 socket：按顺序吐出预置帧，并记录本地发出去的每一帧。"""

    def __init__(self, frames: list[str]) -> None:
        self.sent: list[dict[str, Any]] = []
        self._frames = list(frames)

    async def send(self, frame: str) -> None:
        self.sent.append(json.loads(frame))

    def __aiter__(self) -> FakeSocket:
        return self

    async def __anext__(self) -> str:
        if not self._frames:
            raise StopAsyncIteration
        return self._frames.pop(0)


class FakeConnection:
    """`connect()` 的返回值：异步上下文管理器，进入后给出 socket。"""

    def __init__(self, socket: FakeSocket) -> None:
        self._socket = socket

    async def __aenter__(self) -> FakeSocket:
        return self._socket

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


def _login_ack() -> str:
    return json.dumps({"event": "login", "code": "0", "msg": ""})


def _push(*rows: dict[str, str]) -> str:
    return json.dumps({"arg": {"channel": "fills"}, "data": list(rows)})


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://trading:trading@127.0.0.1:5432/trading",
        okx_api_key=CREDENTIALS.api_key,
        okx_secret_key=CREDENTIALS.secret,
        okx_passphrase=CREDENTIALS.passphrase,
        okx_demo=True,
    )


def _connect_script(*connections: FakeSocket | Exception) -> Callable[[str], FakeConnection]:
    """按顺序返回「成功连接」或抛出异常，用来驱动连续断线。"""

    script: Iterator[FakeSocket | Exception] = iter(connections)

    def connect(_url: str) -> FakeConnection:
        step = next(script)
        if isinstance(step, Exception):
            raise step
        return FakeConnection(step)

    return connect


def _recording_connect(urls: list[str], socket: FakeSocket) -> Callable[[str], FakeConnection]:
    """记录 `connect()` 收到的地址，用来断言模拟盘/实盘各连了哪个域名。"""

    def connect(url: str) -> FakeConnection:
        urls.append(url)
        return FakeConnection(socket)

    return connect


async def _take(client: OkxWebSocket, count: int) -> list[dict[str, Any]]:
    """取前 `count` 行；取够就主动关掉生成器，避免留下未关闭的异步迭代器。"""

    rows: list[dict[str, Any]] = []
    stream = client.messages()
    try:
        async for row in stream:
            rows.append(row)
            if len(rows) == count:
                break
    finally:
        await stream.aclose()
    return rows


# ------------------------------------------------------------------------ 去重


def test_message_key_is_ts_plus_price() -> None:
    assert message_key({"ts": "1794284760000", "fillPx": "100"}) == ("1794284760000", "100")
    assert message_key({"ts": "1794284760000", "px": "100"}) == ("1794284760000", "100")
    assert message_key({"ts": "1794284760000", "price": "100"}) == ("1794284760000", "100")
    assert message_key({"ts": "1794284760000"}) == ("1794284760000", "")


def test_the_same_ts_and_price_is_delivered_once() -> None:
    """上游重连后会重放最近推送：同 `ts` + 同价格只放行一次。"""

    deduper = Deduper()

    assert deduper.accept({"ts": "1", "fillPx": "100"}) is True
    assert deduper.accept({"ts": "1", "fillPx": "100"}) is False
    assert deduper.accept({"ts": "1", "fillPx": "101"}) is True
    assert deduper.accept({"ts": "2", "fillPx": "100"}) is True


def test_rows_without_a_timestamp_are_never_deduplicated() -> None:
    """没有 `ts` 的行无法判重，宁可错放一条，也不能把两笔真实成交抹成一笔。"""

    deduper = Deduper()

    assert deduper.accept({"fillPx": "100"}) is True
    assert deduper.accept({"fillPx": "100"}) is True


def test_the_dedupe_window_is_bounded() -> None:
    """窗口满了之后最早的那条可以被再次放行：内存不随运行时间无限增长。"""

    deduper = Deduper(window=2)

    assert deduper.accept({"ts": "1", "fillPx": "1"}) is True
    assert deduper.accept({"ts": "2", "fillPx": "2"}) is True
    assert deduper.accept({"ts": "3", "fillPx": "3"}) is True
    assert deduper.accept({"ts": "1", "fillPx": "1"}) is True


def test_a_zero_window_is_rejected() -> None:
    with pytest.raises(ValueError):
        Deduper(window=0)


# -------------------------------------------------------------------- 断线重连


def test_demo_settings_connect_to_the_demo_private_endpoint() -> None:
    """`okx_demo=True` 连 `wspap`；连生产地址会让模拟盘登录失败。"""

    urls: list[str] = []
    socket = FakeSocket([_login_ack(), _push({"ts": "1", "fillPx": "100"})])
    client = OkxWebSocket(
        settings=_settings(),
        connect=_recording_connect(urls, socket),
        sleep=_no_sleep(),
    )

    asyncio.run(_take(client, 1))

    assert urls == [OKX_WS_PRIVATE_URL_DEMO]


def test_production_settings_connect_to_the_production_private_endpoint() -> None:
    urls: list[str] = []
    socket = FakeSocket([_login_ack(), _push({"ts": "1", "fillPx": "100"})])
    client = OkxWebSocket(
        settings=_settings().model_copy(update={"okx_demo": False}),
        connect=_recording_connect(urls, socket),
        sleep=_no_sleep(),
    )

    asyncio.run(_take(client, 1))

    assert urls == [OKX_WS_PRIVATE_URL_PROD]


def test_the_configured_url_overrides_the_demo_default() -> None:
    """`OKX_WS_PRIVATE_URL` 显式给出时优先于按 `okx_demo` 推导的地址。"""

    urls: list[str] = []
    socket = FakeSocket([_login_ack(), _push({"ts": "1", "fillPx": "100"})])
    settings = _settings().model_copy(
        update={"okx_ws_private_url": "wss://private.example/ws/v5/private"}
    )
    client = OkxWebSocket(
        settings=settings,
        connect=_recording_connect(urls, socket),
        sleep=_no_sleep(),
    )

    asyncio.run(_take(client, 1))

    assert urls == ["wss://private.example/ws/v5/private"]


def test_the_constructor_url_has_the_highest_priority() -> None:
    urls: list[str] = []
    socket = FakeSocket([_login_ack(), _push({"ts": "1", "fillPx": "100"})])
    client = OkxWebSocket(
        settings=_settings(),
        url="wss://constructor.example/ws/v5/private",
        connect=_recording_connect(urls, socket),
        sleep=_no_sleep(),
    )

    asyncio.run(_take(client, 1))

    assert urls == ["wss://constructor.example/ws/v5/private"]


def test_three_disconnects_then_a_successful_reconnect_without_duplicates() -> None:
    """断线 3 次后第 4 条连接成功，重放的同一行只交出一条。"""

    duplicated = {"ts": "1794284760000", "fillPx": "100"}
    socket = FakeSocket([_login_ack(), _push(duplicated, duplicated)])
    client = OkxWebSocket(
        settings=_settings(),
        connect=_connect_script(
            OSError("断开 1"),
            OSError("断开 2"),
            OSError("断开 3"),
            socket,
        ),
        sleep=_no_sleep(),
        max_attempts=5,
    )

    rows = asyncio.run(_take(client, 1))

    assert rows == [duplicated]


def test_every_connection_only_logs_in_and_subscribes() -> None:
    """重连只发登录与订阅两帧：本类没有下单能力，重连不可能产生订单。"""

    first = FakeSocket([_login_ack()])
    second = FakeSocket([_login_ack(), _push({"ts": "1", "fillPx": "100"})])
    client = OkxWebSocket(
        settings=_settings(),
        connect=_connect_script(OSError("断开"), first, second),
        sleep=_no_sleep(),
    )

    asyncio.run(_take(client, 1))

    for socket in (first, second):
        assert [frame["op"] for frame in socket.sent] == ["login", "subscribe"]
        assert socket.sent[1]["args"] == [dict(channel) for channel in DEFAULT_CHANNELS]


def test_the_login_frame_is_signed() -> None:
    """登录帧带 apiKey / passphrase / 秒级时间戳与签名，签名对固定输入可复现。"""

    socket = FakeSocket([_login_ack(), _push({"ts": "1", "fillPx": "100"})])
    client = OkxWebSocket(settings=_settings(), connect=_connect_script(socket), sleep=_no_sleep())

    asyncio.run(_take(client, 1))

    login = socket.sent[0]["args"][0]
    assert login["apiKey"] == CREDENTIALS.api_key
    assert login["passphrase"] == CREDENTIALS.passphrase
    assert login["timestamp"].isdigit()
    assert login["sign"]


def test_a_normal_close_counts_as_a_disconnect_and_backs_off() -> None:
    """上游正常闭包（不抛异常）也是一次断线：要退避，也要算进连续断开次数。

    `websockets` 在关闭码 1000/1001 时让异步迭代器正常结束，不抛异常。如果只把异常
    当断线，这里会立刻重连，每一轮都重新登录并订阅，变成没有间隔的热循环。
    """

    first = FakeSocket([_login_ack()])
    second = FakeSocket([_login_ack(), _push({"ts": "1", "fillPx": "100"})])
    sleeps: list[float] = []
    client = OkxWebSocket(
        settings=_settings(),
        connect=_connect_script(first, second),
        sleep=_recording_sleep(sleeps),
        backoff_seconds=0.5,
    )

    rows = asyncio.run(_take(client, 1))

    assert rows == [{"ts": "1", "fillPx": "100"}]
    assert sleeps == [0.5], "正常关闭也必须退避一次再重连"


def test_normal_closes_are_bounded_by_the_attempt_limit() -> None:
    """正常关闭反复发生时同样会放弃：没有数据进来就不重置计数。"""

    sockets = [FakeSocket([_login_ack()]) for _ in range(4)]
    client = OkxWebSocket(
        settings=_settings(),
        connect=_connect_script(*sockets),
        sleep=_no_sleep(),
        max_attempts=2,
    )

    with pytest.raises(ExchangeError):
        asyncio.run(_take(client, 1))


def test_reconnect_gives_up_after_the_attempt_limit() -> None:
    client = OkxWebSocket(
        settings=_settings(),
        connect=_connect_script(OSError("断开 1"), OSError("断开 2"), OSError("断开 3")),
        sleep=_no_sleep(),
        max_attempts=2,
    )

    with pytest.raises(ExchangeError):
        asyncio.run(_take(client, 1))


def test_a_failed_login_is_reported_instead_of_retried() -> None:
    """登录回执非 0 是凭据问题，重连多少次都一样，直接抛出去让调用方处理。"""

    socket = FakeSocket([json.dumps({"event": "login", "code": "50113", "msg": "Invalid Sign"})])
    client = OkxWebSocket(settings=_settings(), connect=_connect_script(socket), sleep=_no_sleep())

    with pytest.raises(ExchangeError):
        asyncio.run(_take(client, 1))


def test_missing_credentials_are_rejected_at_construction() -> None:
    """口令缺失在构造阶段就报错：不必等到连上之后才发现登录必然失败。"""

    settings = _settings().model_copy(update={"okx_passphrase": ""})

    with pytest.raises(ValidationError):
        OkxWebSocket(settings=settings, connect=_connect_script())


def _recording_sleep(sleeps: list[float]) -> Any:
    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return sleep


def _no_sleep() -> Any:
    async def sleep(_seconds: float) -> None:
        return None

    return sleep

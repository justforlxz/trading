"""公共行情 WebSocket：订阅增删、断线重连、重放去重与状态回调。

用脚本化的假连接驱动，不连真实网络，也不真的等待退避时间。
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from app.exchange import ExchangeError, MarketPush, OkxPublicWebSocket


class FakeSocket:
    """假的已连接 socket：按顺序吐出帧，帧用完可以选择一直阻塞。"""

    def __init__(self, frames: list[str], *, block_when_empty: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self._frames = deque(frames)
        self._block = block_when_empty

    async def send(self, frame: str) -> None:
        self.sent.append(json.loads(frame))

    async def recv(self) -> str:
        if self._frames:
            return self._frames.popleft()
        if self._block:
            await asyncio.Event().wait()
        raise OSError("连接关闭")


class FakeConnection:
    def __init__(self, socket: FakeSocket) -> None:
        self._socket = socket

    async def __aenter__(self) -> FakeSocket:
        return self._socket

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


def _connect_script(*steps: FakeSocket | Exception) -> Callable[[str], FakeConnection]:
    queue: Iterator[FakeSocket | Exception] = iter(steps)

    def connect(_url: str) -> FakeConnection:
        step = next(queue)
        if isinstance(step, Exception):
            raise step
        return FakeConnection(step)

    return connect


def _push(channel: str, inst_id: str, ts: str, **fields: str) -> str:
    return json.dumps(
        {"arg": {"channel": channel}, "data": [{"instId": inst_id, "ts": ts, **fields}]}
    )


async def _take(client: OkxPublicWebSocket, count: int) -> list[MarketPush]:
    rows: list[MarketPush] = []
    stream = client.messages()
    try:
        async for push in stream:
            rows.append(push)
            if len(rows) == count:
                break
    finally:
        await stream.aclose()
    return rows


def _no_sleep() -> Any:
    async def sleep(_seconds: float) -> None:
        return None

    return sleep


def test_subscribe_frame_covers_three_channels_and_reconnect_resubscribes() -> None:
    first = FakeSocket([_push("tickers", "XAAPL-USDT", "1", last="100")])
    second = FakeSocket([_push("tickers", "XAAPL-USDT", "2", last="101")], block_when_empty=True)
    statuses: list[tuple[bool, str]] = []
    client = OkxPublicWebSocket(
        connect=_connect_script(first, second),
        sleep=_no_sleep(),
        on_status=lambda connected, error: statuses.append((connected, error)),
    )
    client.set_instruments({"XAAPL-USDT"})

    rows = asyncio.run(_take(client, 2))

    assert [row.row["last"] for row in rows] == ["100", "101"]
    expected_args = [
        {"channel": channel, "instId": "XAAPL-USDT"}
        for channel in ("tickers", "mark-price", "index-tickers")
    ]
    assert first.sent[0] == {"op": "subscribe", "args": expected_args}
    assert second.sent[0] == {"op": "subscribe", "args": expected_args}
    assert (True, "") in statuses
    assert statuses[0] == (True, "")
    assert any(connected is False for connected, _error in statuses)


def test_replayed_message_with_the_same_ts_is_delivered_once() -> None:
    frame = _push("tickers", "XAAPL-USDT", "1794284760000", last="231.42")
    socket = FakeSocket([frame, frame], block_when_empty=True)
    client = OkxPublicWebSocket(connect=_connect_script(socket), sleep=_no_sleep())
    client.set_instruments({"XAAPL-USDT"})

    async def scenario() -> None:
        stream = client.messages()
        try:
            first = await asyncio.wait_for(anext(stream), timeout=1.0)
            assert first.row["last"] == "231.42"
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(anext(stream), timeout=0.05)
        finally:
            await stream.aclose()

    asyncio.run(scenario())


def test_unsubscribed_instruments_are_filtered_out() -> None:
    socket = FakeSocket(
        [
            _push("tickers", "OTHER-USDT", "1", last="9"),
            _push("tickers", "XAAPL-USDT", "2", last="231.42"),
        ],
        block_when_empty=True,
    )
    client = OkxPublicWebSocket(connect=_connect_script(socket), sleep=_no_sleep())
    client.set_instruments({"XAAPL-USDT"})

    rows = asyncio.run(_take(client, 1))

    assert [(row.inst_id, row.row["last"]) for row in rows] == [("XAAPL-USDT", "231.42")]


def test_gives_up_after_the_attempt_limit() -> None:
    client = OkxPublicWebSocket(
        connect=_connect_script(OSError("断开 1"), OSError("断开 2")),
        sleep=_no_sleep(),
        max_attempts=1,
    )
    client.set_instruments({"XAAPL-USDT"})

    with pytest.raises(ExchangeError):
        asyncio.run(_take(client, 1))

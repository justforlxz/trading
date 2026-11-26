"""公共行情 WebSocket：订阅增删、断线重连、重放去重与状态回调。

用脚本化的假连接驱动，不连真实网络，也不真的等待退避时间。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest

from app.exchange import ExchangeError, MarketPush, OkxPublicWebSocket, candle_channel
from app.exchange.okx.market_ws import (
    DEFAULT_BUSINESS_WS_URL,
    DEFAULT_PUBLIC_WS_URL,
    MAX_SUBSCRIBE_FRAME_BYTES,
    SUBSCRIBE_FRAME_SAFETY_MARGIN,
    _frame,
    fit_subscription,
)


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


def test_swap_instruments_skip_the_index_channel() -> None:
    """`index-tickers` 只接受指数标识（现货形态）；永续标识被上游以 60018 拒绝。

    两种形态以前按同一组频道订阅，日志里持续刷「instId:XXX-USDT-SWAP doesn't
    exist」。指数价对永续本来也没有对应标识，这里直接不订。
    """

    socket = FakeSocket([_push("tickers", "XAAPL-USDT", "1", last="100")], block_when_empty=True)
    client = OkxPublicWebSocket(connect=_connect_script(socket), sleep=_no_sleep())
    client.set_instruments({"XAAPL-USDT", "AAPL-USDT-SWAP"})

    asyncio.run(_take(client, 1))

    args = socket.sent[0]["args"]
    assert {"channel": "index-tickers", "instId": "AAPL-USDT-SWAP"} not in args
    assert {"channel": "index-tickers", "instId": "XAAPL-USDT"} in args
    assert {"channel": "tickers", "instId": "AAPL-USDT-SWAP"} in args
    assert {"channel": "mark-price", "instId": "AAPL-USDT-SWAP"} in args


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


# ---------------------------------------------------------------- K 线频道


def _candle_push(inst_id: str, ts: str, *, confirm: str, close: str = "100") -> str:
    return json.dumps(
        {
            "arg": {"channel": "candle1H", "instId": inst_id},
            "data": [[ts, "90", "110", "80", close, "12", "12", "1200", confirm]],
        }
    )


def test_candle_channel_is_subscribed_next_to_the_quote_channels() -> None:
    """AC1：K 线另开一条连接，订阅帧里是 `candle1H`，推送按九列数组解析。"""

    socket = FakeSocket(
        [_candle_push("XAAPL-USDT", "1794284760000", confirm="1")], block_when_empty=True
    )
    client = OkxPublicWebSocket(
        connect=_connect_script(socket),
        sleep=_no_sleep(),
        channels=(candle_channel("1h"),),
    )
    client.set_instruments({"XAAPL-USDT"})

    rows = asyncio.run(_take(client, 1))

    assert socket.sent[0] == {
        "op": "subscribe",
        "args": [{"channel": "candle1H", "instId": "XAAPL-USDT"}],
    }
    candle = rows[0].candle
    assert candle is not None
    assert (rows[0].inst_id, candle.bar, candle.confirm) == ("XAAPL-USDT", "1h", True)
    assert candle.close == Decimal("100")
    assert candle.open_time.timestamp() == 1794284760


def test_a_forming_candle_does_not_swallow_the_closed_one_for_the_same_bar() -> None:
    """同一根 K 线先推 confirm=0、再推 confirm=1：收盘那根不能被当成重放丢掉。"""

    socket = FakeSocket(
        [
            _candle_push("XAAPL-USDT", "1794284760000", confirm="0", close="99"),
            _candle_push("XAAPL-USDT", "1794284760000", confirm="1", close="100"),
            _candle_push("XAAPL-USDT", "1794284760000", confirm="1", close="100"),
        ],
        block_when_empty=True,
    )
    client = OkxPublicWebSocket(
        connect=_connect_script(socket),
        sleep=_no_sleep(),
        channels=(candle_channel("1h"),),
    )
    client.set_instruments({"XAAPL-USDT"})

    rows = asyncio.run(_take(client, 2))

    assert [(row.candle.confirm, row.candle.close) for row in rows if row.candle] == [
        (False, Decimal("99")),
        (True, Decimal("100")),
    ]


def _frame_size(
    inst_ids: tuple[str, ...], channels: tuple[str, ...], *, op: str = "subscribe"
) -> int:
    return len(json.dumps(_frame(op, inst_ids, channels)).encode())


def test_a_truncated_frame_really_fits_the_upstream_limit() -> None:
    """AC5 回归：截断后的帧本身必须装得下。

    旧实现按「参数字节 + 1」累加，实际帧比估算多 `参数数 - 2` 字节（参数之间是 `", "`），
    于是一旦触发截断，帧必然超过 64 KB，上游以 `1009 (message too big)` 关掉连接，
    一个标的都订不上。
    """

    channels = ("tickers", "mark-price", "index-tickers", "candle1H")
    ordered = tuple(f"INST{index:04d}-USDT-SWAP" for index in range(2000))

    kept, skipped = fit_subscription(ordered, channels)

    assert skipped == 2000 - len(kept)
    assert 0 < len(kept) < 2000
    assert _frame_size(kept, channels) <= MAX_SUBSCRIBE_FRAME_BYTES - SUBSCRIBE_FRAME_SAFETY_MARGIN
    # 再放一个就超限：保留的是能装下的最长前缀，不是保守地少订一堆。
    assert _frame_size((*kept, ordered[len(kept)]), channels) > (
        MAX_SUBSCRIBE_FRAME_BYTES - SUBSCRIBE_FRAME_SAFETY_MARGIN
    )


def test_the_truncation_keeps_the_priority_order_and_reports_the_rest() -> None:
    """装不下的标的按给定顺序从尾部截断，跳过数量可读，不静默丢弃。"""

    channels = ("candle1H",)
    ordered = tuple(f"INST{index:04d}-USDT-SWAP" for index in range(400))
    # 预算按实现使用的 op（`unsubscribe`，比 `subscribe` 长两字节）量，正好装 5 个。
    budget = _frame_size(ordered[:5], channels, op="unsubscribe")

    kept, skipped = fit_subscription(ordered, channels, budget=budget)

    assert kept == ordered[:5]
    assert skipped == 395


def test_a_client_that_does_not_fit_everything_reports_the_skipped_count() -> None:
    """`skipped` 来自连接自身：健康接口读它，不靠调用方估算。"""

    client = OkxPublicWebSocket(
        connect=_connect_script(FakeSocket([], block_when_empty=True)),
        sleep=_no_sleep(),
        channels=(candle_channel("1h"),),
    )
    client.set_instruments(["B-USDT", "A-USDT"])

    assert client.subscriptions == ("B-USDT", "A-USDT")
    assert client.skipped == 0


def test_an_upstream_subscription_error_is_logged_and_yields_no_push(caplog) -> None:
    """上游拒绝某个频道时必须留痕：不能静默当作「没有推送」。"""

    socket = FakeSocket(
        [
            json.dumps({"event": "error", "code": "60018", "msg": "doesn't exist"}),
            _push("tickers", "XAAPL-USDT", "1", last="100"),
        ],
        block_when_empty=True,
    )
    client = OkxPublicWebSocket(connect=_connect_script(socket), sleep=_no_sleep())
    client.set_instruments({"XAAPL-USDT"})

    with caplog.at_level(logging.WARNING):
        rows = asyncio.run(_take(client, 1))

    assert [row.row["last"] for row in rows] == ["100"]
    assert "60018" in caplog.text


def test_the_default_public_endpoints_use_the_migrated_port() -> None:
    """上游公告 8443 将退役（推送 64010）：行情与 K 线两条连接默认走 443。"""

    assert DEFAULT_PUBLIC_WS_URL == "wss://ws.okx.com:443/ws/v5/public"
    assert DEFAULT_BUSINESS_WS_URL == "wss://ws.okx.com:443/ws/v5/business"

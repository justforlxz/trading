"""OKX 私有 WebSocket：登录、订阅、断线重连、按 `ts` + `price` 去重。

上游在重连之后会重放最近一段推送，只靠「收到即处理」会把同一笔成交换算两次。
本模块因此把「去重」放在推进入口：同一个 `ts` + `price` 的行只放行一次。窗口是
有限的（默认 1024 条）：去重只需要覆盖重连前后的重叠段，无界集合会随进程运行
时间一起长下去。

重连只重做两件事：登录、重新订阅。它**不下单**——`OkxWebSocket` 手上没有交易端口，
「重连不产生重复订单」因此是结构上的事实，而不是靠调用方记得别下单。

`connect` / `sleep` / `clock` 都可注入：测试用假连接驱动「连续断线 3 次再成功」，
不连真实网络，也不真的等退避时间。
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

import websockets
from websockets.asyncio.client import connect as ws_connect

from app.config import Settings, get_settings
from app.core import Clock, SystemClock
from app.exchange.errors import ExchangeError
from app.exchange.okx.sign import require_credentials, ws_login_signature

__all__ = [
    "DEFAULT_CHANNELS",
    "Deduper",
    "OkxWebSocket",
    "message_key",
]

#: 连续失败多少次之后放弃重连，把错误抛给上层。
MAX_RECONNECT_ATTEMPTS = 5
#: 首次重连的等待秒数，之后按 2 的幂递增。
RECONNECT_BASE_SECONDS = 0.5
#: 去重窗口：够覆盖重连前后的重叠段，又不会随运行时间无限增长。
DEDUPE_WINDOW = 1024
#: 私有频道：订单、成交、持仓、账户余额。
DEFAULT_CHANNELS: tuple[dict[str, str], ...] = (
    {"channel": "orders"},
    {"channel": "fills"},
    # `positions` 频道必须声明 instType；缺省时上游返回 60018「频道不存在」。
    {"channel": "positions", "instType": "SWAP"},
    {"channel": "account"},
)

#: 推送里表示价格的字段：不同频道叫法不同，按顺序取第一个有值的。
_PRICE_FIELDS = ("price", "px", "fillPx", "markPx", "last")
#: 连接层的可重试异常：网络断开、握手失败。
RECONNECT_ON: tuple[type[BaseException], ...] = (
    websockets.exceptions.WebSocketException,
    OSError,
)


def message_key(row: dict[str, Any]) -> tuple[str, str]:
    """一条推送的去重键：`(ts, price)`；缺字段时用空串占位。"""

    price = ""
    for field in _PRICE_FIELDS:
        value = row.get(field)
        if value is not None and str(value) != "":
            price = str(value)
            break
    return str(row.get("ts") or ""), price


class Deduper:
    """按 `ts` + `price` 去重的滑动窗口。"""

    def __init__(self, window: int = DEDUPE_WINDOW) -> None:
        if window < 1:
            raise ValueError("去重窗口必须为正整数")
        self._order: deque[tuple[str, str]] = deque(maxlen=window)
        self._seen: set[tuple[str, str]] = set()

    def accept(self, row: dict[str, Any]) -> bool:
        """这条推送是不是新的；同键第二次到达返回 `False`。

        没有 `ts` 的行无法判重（不同频道的推送未必都带时间戳），一律放行：
        宁可错放一条，也不能把两笔真实成交当成一笔抹掉。
        """

        key = message_key(row)
        if not key[0]:
            return True
        if key in self._seen:
            return False
        if len(self._order) == self._order.maxlen:
            self._seen.discard(self._order[0])
        self._order.append(key)
        self._seen.add(key)
        return True


class OkxWebSocket:
    """私有频道推送流：登录 → 订阅 → 断线重连。

    用法是一个异步迭代器：`async for row in client.messages()`。每次重连都会重新
    登录并重新订阅，收到的行按 `Deduper` 去重后逐个交出。
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        channels: Sequence[dict[str, str]] | None = None,
        url: str | None = None,
        connect: Callable[..., Any] = ws_connect,
        clock: Clock | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_attempts: int = MAX_RECONNECT_ATTEMPTS,
        backoff_seconds: float = RECONNECT_BASE_SECONDS,
        deduper: Deduper | None = None,
        on_status: Callable[[bool, str], None] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._channels = tuple(channels) if channels is not None else DEFAULT_CHANNELS
        # 未显式给地址时按 `okx_demo` 推导：模拟盘连 `wspap`，实盘连 `ws`。
        self._url = url or self._settings.ws_private_url
        self._connect = connect
        self._clock = clock or SystemClock()
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._deduper = deduper or Deduper()
        self._on_status = on_status
        require_credentials(self._settings)

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        """只交出数据行；频道名由 `channel_messages` 提供。"""

        async for _channel, rows in self.channel_messages():
            for row in rows:
                yield row

    async def channel_messages(self) -> AsyncIterator[tuple[str, list[dict[str, Any]]]]:
        """按上游封包交出 `(频道, 数据行列表)`；连续断开超过上限时抛 `ExchangeError`。

        「断开」包含两种形态：连接层抛异常，以及上游以正常闭包（关闭码 1000/1001，
        例如维护、重启、登录会话到期）结束迭代。后者不抛异常，如果只把异常当断线，
        `while True` 就会立刻重连——每一次都重新登录并订阅，变成没有间隔的热循环。
        因此正常结束与异常走同一套计数与退避；只有真正收到推送行才把计数清零。
        """

        attempt = 0
        while True:
            reason = ""
            try:
                async with self._connect(self._url) as socket:
                    await self._handshake(socket)
                    self._notify(True, "")
                    async for raw in socket:
                        channel, rows = _channel_rows(raw)
                        fresh = [row for row in rows if self._deduper.accept(row)]
                        if fresh:
                            # 收到行才说明这条连接真的通了：把连续断开计数清零。
                            attempt = 0
                            yield channel, fresh
            except RECONNECT_ON as exc:
                reason = str(exc)
            else:
                reason = "上游正常关闭连接"
            self._notify(False, reason)
            if attempt >= self._max_attempts:
                raise ExchangeError(f"WebSocket 连续断开 {attempt} 次后放弃重连:{reason}")
            await self._sleep(self._backoff * 2**attempt)
            attempt += 1

    def _notify(self, connected: bool, error: str) -> None:
        if self._on_status is not None:
            self._on_status(connected, error)

    async def _handshake(self, socket: Any) -> None:
        """登录并等到回执，然后订阅；登录失败立刻报错，不进入收流阶段。"""

        await socket.send(json.dumps(self._login_frame()))
        async for raw in socket:
            message = json.loads(raw)
            if message.get("event") != "login":
                continue
            if str(message.get("code") or "") != "0":
                raise ExchangeError(
                    f"WebSocket 登录失败 {message.get('code')}:{message.get('msg') or '未给出原因'}"
                )
            break
        else:
            raise ExchangeError("WebSocket 在登录回执之前就关闭了")
        await socket.send(json.dumps(self._subscribe_frame()))

    def _login_frame(self) -> dict[str, Any]:
        epoch = int(self._clock.now().timestamp())
        return {
            "op": "login",
            "args": [
                {
                    "apiKey": self._settings.okx_api_key,
                    "passphrase": self._settings.okx_passphrase,
                    "timestamp": str(epoch),
                    "sign": ws_login_signature(self._settings.okx_secret_key, epoch_seconds=epoch),
                }
            ],
        }

    def _subscribe_frame(self) -> dict[str, Any]:
        return {"op": "subscribe", "args": [dict(channel) for channel in self._channels]}


def _rows(raw: str | bytes) -> list[dict[str, Any]]:
    """上游推送封包 `{"arg": …, "data": [ … ]}` → 逐行数据。"""

    return _channel_rows(raw)[1]


def _channel_rows(raw: str | bytes) -> tuple[str, list[dict[str, Any]]]:
    """上游推送封包 → `(频道, 逐行数据)`；频道名用于区分账户与持仓。"""

    try:
        message = json.loads(raw)
    except ValueError as exc:
        raise ExchangeError("推送不是合法 JSON") from exc
    if not isinstance(message, dict):
        raise ExchangeError("推送结构异常")
    arg = message.get("arg")
    channel = str(arg.get("channel") or "") if isinstance(arg, dict) else ""
    data = message.get("data")
    if not isinstance(data, list):
        return channel, []
    return channel, [row for row in data if isinstance(row, dict)]

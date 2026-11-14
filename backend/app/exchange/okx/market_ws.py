"""OKX 公共行情 WebSocket 与 REST 初始快照。

浏览器不直接连交易所：本模块只负责和 OKX 公共频道通信，把推送整理成
`MarketPush`（频道、标的、原始行）。订阅集合由上层订阅管理器决定，`set_instruments`
可以在连接期间增删标的：新增立即订阅、移除立即退订，重连时按当前集合重新订阅。

`tickers` / `mark-price` / `index-tickers` 三个频道的字段名不同，本层不合并成业务
行情；合并与去重属于 `app.stream`，因为节流和“只推客户端订阅的标的”是推送层的
规则，不是交易所适配层的规则。

重连沿用私有客户端的同一套口径：有上限的指数退避，收到推送才把连续断开计数清零。
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from websockets.asyncio.client import connect as ws_connect

from app.config import Settings
from app.exchange.errors import ExchangeError
from app.exchange.okx.client import OkxClient
from app.exchange.okx.ws import MAX_RECONNECT_ATTEMPTS, RECONNECT_BASE_SECONDS, RECONNECT_ON

__all__ = [
    "DEFAULT_PUBLIC_CHANNELS",
    "DEFAULT_PUBLIC_WS_URL",
    "MarketPush",
    "OkxPublicWebSocket",
    "load_quote_snapshot",
]

#: OKX 公共频道地址。
DEFAULT_PUBLIC_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
#: 行情需要的三个频道；同一个 inst_id 在每个频道各订阅一次。
DEFAULT_PUBLIC_CHANNELS: tuple[str, ...] = ("tickers", "mark-price", "index-tickers")
#: 去重窗口：覆盖重连后的重放段，又不随进程运行时间无限增长。
DEDUPE_WINDOW = 2048

_TICKER_PATH = "/api/v5/market/ticker"
_MARK_PRICE_PATH = "/api/v5/public/mark-price"
_INDEX_TICKERS_PATH = "/api/v5/market/index-tickers"

StatusCallback = Callable[[bool, str], None]


@dataclass(frozen=True, slots=True)
class MarketPush:
    """一条行情推送：上游频道、标的与原始数据行。"""

    channel: str
    inst_id: str
    row: dict[str, Any]


class _Seen:
    """按 `(频道, 标的, 时间戳)` 去重的滑动窗口。"""

    def __init__(self, window: int = DEDUPE_WINDOW) -> None:
        if window < 1:
            raise ValueError("去重窗口必须为正整数")
        self._order: deque[tuple[str, str, str]] = deque(maxlen=window)
        self._seen: set[tuple[str, str, str]] = set()

    def accept(self, key: tuple[str, str, str]) -> bool:
        if not key[2]:
            return True
        if key in self._seen:
            return False
        if len(self._order) == self._order.maxlen:
            self._seen.discard(self._order[0])
        self._order.append(key)
        self._seen.add(key)
        return True


class OkxPublicWebSocket:
    """公共行情推送流：按订阅集合连接、增删订阅、断线重连。

    用法：

    ```python
    client = OkxPublicWebSocket()
    client.set_instruments({"XAAPL-USDT"})
    async for push in client.messages():
        ...
    ```
    """

    def __init__(
        self,
        *,
        url: str = DEFAULT_PUBLIC_WS_URL,
        connect: Callable[..., Any] = ws_connect,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_attempts: int = MAX_RECONNECT_ATTEMPTS,
        backoff_seconds: float = RECONNECT_BASE_SECONDS,
        dedupe_window: int = DEDUPE_WINDOW,
        on_status: StatusCallback | None = None,
    ) -> None:
        self._url = url
        self._connect = connect
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._deduper = _Seen(dedupe_window)
        self._on_status = on_status
        self._instruments: set[str] = set()
        self._changed = asyncio.Event()

    def set_instruments(self, inst_ids: Iterable[str]) -> None:
        """替换订阅集合；连接中会立即增删订阅，重连时按这个集合重新订阅。"""

        self._instruments = {item for item in inst_ids if item}
        self._changed.set()

    async def messages(self) -> AsyncIterator[MarketPush]:
        """推送行的异步迭代器；连续断开超过上限时抛 `ExchangeError`。"""

        attempt = 0
        while True:
            reason = ""
            current: set[str] = set()
            self._changed.clear()
            try:
                async with self._connect(self._url) as socket:
                    current = set(self._instruments)
                    await self._change_subscriptions(socket, added=current, removed=set())
                    self._notify(True, "")
                    while True:
                        receive = asyncio.create_task(socket.recv())
                        changed = asyncio.create_task(self._changed.wait())
                        try:
                            done, _pending = await asyncio.wait(
                                {receive, changed}, return_when=asyncio.FIRST_COMPLETED
                            )
                        finally:
                            for task in (receive, changed):
                                task.cancel()
                        await asyncio.gather(receive, changed, return_exceptions=True)
                        pushes: list[MarketPush] = []
                        if receive in done:
                            attempt = 0
                            pushes = _parse_push(receive.result())
                        if changed in done:
                            wanted = set(self._instruments)
                            await self._change_subscriptions(
                                socket,
                                added=wanted - current,
                                removed=current - wanted,
                            )
                            current = wanted
                            self._changed.clear()
                        for push in pushes:
                            if push.inst_id not in current or push.inst_id not in self._instruments:
                                continue
                            key = (push.channel, push.inst_id, str(push.row.get("ts") or ""))
                            if self._deduper.accept(key):
                                yield push
            except RECONNECT_ON as exc:
                reason = str(exc)
            else:
                reason = "上游正常关闭连接"
            self._notify(False, reason)
            if attempt >= self._max_attempts:
                raise ExchangeError(f"公共 WebSocket 连续断开 {attempt} 次后放弃重连:{reason}")
            await self._sleep(self._backoff * 2**attempt)
            attempt += 1

    async def _change_subscriptions(
        self,
        socket: Any,
        *,
        added: set[str],
        removed: set[str],
    ) -> None:
        """把新增与移除的标的换算成 subscribe / unsubscribe 帧。"""

        if added:
            await socket.send(json.dumps(_frame("subscribe", sorted(added))))
        if removed:
            await socket.send(json.dumps(_frame("unsubscribe", sorted(removed))))

    def _notify(self, connected: bool, error: str) -> None:
        if self._on_status is not None:
            self._on_status(connected, error)


def _frame(operation: str, inst_ids: Iterable[str]) -> dict[str, Any]:
    return {
        "op": operation,
        "args": [
            {"channel": channel, "instId": inst_id}
            for inst_id in inst_ids
            for channel in DEFAULT_PUBLIC_CHANNELS
        ],
    }


def _parse_push(raw: str | bytes) -> list[MarketPush]:
    try:
        message = json.loads(raw)
    except ValueError as exc:
        raise ExchangeError("公共推送不是合法 JSON") from exc
    if not isinstance(message, dict):
        raise ExchangeError("公共推送结构异常")
    arg = message.get("arg")
    channel = str(arg.get("channel") or "") if isinstance(arg, dict) else ""
    data = message.get("data")
    if not isinstance(data, list):
        return []
    pushes: list[MarketPush] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        inst_id = str(row.get("instId") or "")
        if inst_id:
            pushes.append(MarketPush(channel=channel, inst_id=inst_id, row=row))
    return pushes


def load_quote_snapshot(
    inst_ids: Iterable[str],
    *,
    settings: Settings | None = None,
    client: OkxClient | None = None,
) -> list[dict[str, Any]]:
    """REST 行情快照：每个标的合并 last / mark / index 三个价格。

    单个价格取不到不影响其余字段；上游故障与不支持该频道的标的都按“该字段缺失”
    处理，不拿相似标的或上一次的值冒充。返回 `ts` 为毫秒时间戳，交给推送层统一
    换算成带时区的时间。
    """

    own_client = client is None
    rest = client or OkxClient(settings=settings)
    rows: list[dict[str, Any]] = []
    try:
        for inst_id in inst_ids:
            values: dict[str, Any] = {"inst_id": inst_id, "ts": 0}
            ticker = _first(rest, _TICKER_PATH, {"instId": inst_id})
            if ticker is not None:
                values["last"] = ticker.get("last")
                values["ts"] = _latest_ts(values["ts"], ticker.get("ts"))
            mark = _first(rest, _MARK_PRICE_PATH, {"instType": "SWAP", "instId": inst_id})
            if mark is not None:
                values["mark"] = mark.get("markPx")
                values["ts"] = _latest_ts(values["ts"], mark.get("ts"))
            index = _first(rest, _INDEX_TICKERS_PATH, {"instId": inst_id})
            if index is not None:
                values["index"] = index.get("idxPx")
                values["ts"] = _latest_ts(values["ts"], index.get("ts"))
            if any(field in values for field in ("last", "mark", "index")):
                rows.append(values)
    finally:
        if own_client:
            rest.close()
    return rows


def _first(client: OkxClient, path: str, params: dict[str, str]) -> dict[str, Any] | None:
    try:
        rows = client.get(path, params)
    except ExchangeError:
        return None
    if not rows or not isinstance(rows[0], dict):
        return None
    return rows[0]


def _latest_ts(current: Any, candidate: Any) -> int:
    try:
        value = int(candidate)
    except (TypeError, ValueError):
        return int(current or 0)
    return max(int(current or 0), value)

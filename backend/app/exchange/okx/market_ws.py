"""OKX 公共行情 WebSocket 与 REST 初始快照。

浏览器不直接连交易所：本模块只负责和 OKX 公共频道通信，把推送整理成
`MarketPush`（频道、标的、原始行）。订阅集合由上层订阅管理器决定，`set_instruments`
可以在连接期间增删标的：新增立即订阅、移除立即退订，重连时按当前集合重新订阅。

`tickers` / `mark-price` / `index-tickers` 三个频道的字段名不同，本层不合并成业务
行情；合并与去重属于 `app.stream`，因为节流和“只推客户端订阅的标的”是推送层的
规则，不是交易所适配层的规则。

重连沿用私有客户端的同一套口径：有上限的指数退避，收到推送才把连续断开计数清零。

## 两组频道、两个地址

`tickers` / `mark-price` / `index-tickers` 在公共行情地址（`/ws/v5/public`）；
`candle{周期}` 只在业务地址（`/ws/v5/business`）。2026-11-21 实测：同一个标的的
`candle1H` 向公共地址订阅会被上游以 `60018`（频道或标的参数不对）拒绝，向业务地址
订阅立刻返回 K 线推送。因此推送层对同一个标的集合开两条连接，本模块用 `channels`
参数区分它们，解析与重连逻辑完全共用。

## 上游的单连接限制（官方 WebSocket 文档，2026-11-21 核对）

- 单次订阅请求里多个频道的总长度不超过 64 KB（实测 61,301 字节被接受，66,227 字节
  被以 `1009 (message too big)` 关闭，因此内部按 64 KB 减 1 KB 的余量安排）；
- 每条连接的 `subscribe` / `unsubscribe` / `login` 合计不超过 480 次/小时；
- 公共频道没有「频道数量」上限（只有订单、账户、持仓等六个私有频道有每子账户
  30 条连接的限制）。

所以「超限」的具体含义是这一次请求装不下：`fit_subscription` 按调用方给的优先级，
用**序列化后的真实帧长度**（不是逐参数累加）二分出装得下的最长前缀，装不下的标的返回
跳过数量，由健康接口显示，不静默丢弃。默认 1796 个标的的行情连接会保留约 370 个，
K 线连接约 1330 个。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from websockets.asyncio.client import connect as ws_connect

from app.config import Settings
from app.core import utc_from_millis
from app.exchange.errors import ExchangeError
from app.exchange.okx.bars import from_okx_bar, to_okx_bar
from app.exchange.okx.client import OkxClient
from app.exchange.okx.ws import MAX_RECONNECT_ATTEMPTS, RECONNECT_BASE_SECONDS, RECONNECT_ON

__all__ = [
    "DEFAULT_BUSINESS_WS_URL",
    "DEFAULT_PUBLIC_CHANNELS",
    "DEFAULT_PUBLIC_WS_URL",
    "MAX_SUBSCRIBE_FRAME_BYTES",
    "CandleShape",
    "MarketPush",
    "OkxPublicWebSocket",
    "candle_channel",
    "fit_subscription",
    "load_quote_snapshot",
]

#: OKX 公共行情地址：`tickers` / `mark-price` / `index-tickers`。上游已公告 `8443`
#: 将退役，默认改走 `443`。
DEFAULT_PUBLIC_WS_URL = "wss://ws.okx.com:443/ws/v5/public"
#: OKX 业务地址：K 线（`candle{周期}`）只在这里推送，公共地址会以 60018 拒绝。
DEFAULT_BUSINESS_WS_URL = "wss://ws.okx.com:443/ws/v5/business"
#: 行情需要的三个频道；同一个 inst_id 在每个频道各订阅一次（`index-tickers` 例外，
#: 见 `_channels_for`）。
DEFAULT_PUBLIC_CHANNELS: tuple[str, ...] = ("tickers", "mark-price", "index-tickers")
#: 上游按 `instId` 指认标的；永续标识带这个后缀（`AAPL-USDT-SWAP`）。
SWAP_INST_SUFFIX = "-SWAP"
INDEX_TICKERS_CHANNEL = "index-tickers"
#: 上游对单次订阅请求的长度上限：多个频道的 `args` 总长度不超过 64 KB。
MAX_SUBSCRIBE_FRAME_BYTES = 64 * 1024
#: 给上限留的余量。上游文档只写「64 KB」，实测 61,301 字节被接受、66,227 字节被以
#: `1009 (message too big)` 关闭，边界值不必踩满：少订二十来个标的换连接不被断。
SUBSCRIBE_FRAME_SAFETY_MARGIN = 1024
#: 去重窗口：覆盖重连后的重放段，又不随进程运行时间无限增长。
DEDUPE_WINDOW = 2048

logger = logging.getLogger(__name__)


def candle_channel(bar: str) -> str:
    """内部周期 → OKX K 线频道名；上游的 `H`/`D` 大写写法只在本层转换。"""

    return f"candle{to_okx_bar(bar)}"


def fit_subscription(
    inst_ids: Iterable[str],
    channels: Sequence[str],
    *,
    budget: int = MAX_SUBSCRIBE_FRAME_BYTES - SUBSCRIBE_FRAME_SAFETY_MARGIN,
) -> tuple[tuple[str, ...], int]:
    """按给定顺序装进一次订阅请求，返回（保留的标的, 跳过的数量）。

    `budget` 按**序列化后的真实帧**量，不靠逐参数累加估算：参数之间是 `", "`（两个
    字节），首尾结构各占定长，估算出来的数会比实际帧少 `参数数 - 2` 字节——一旦触发
    截断，帧必然超限，上游会以 `1009 (message too big)` 直接关掉连接，一个标的都订不上。

    帧长度随标的数量单调递增，因此对「保留前几个」二分，取真正装得下的最长前缀。
    按顺序装入而不是挑挑拣拣：调用方给的就是优先级（关注列表在前、只在浏览器里打开的
    在后的标的会被先截掉）。`unsubscribe` 的 op 名比 `subscribe` 长两个字节，按前者量
    给退订帧也留出余量。
    """

    ordered = tuple(dict.fromkeys(item for item in inst_ids if item))
    low, high = 0, len(ordered)
    while low < high:
        middle = (low + high + 1) // 2
        if _frame_bytes(ordered[:middle], channels) <= budget:
            low = middle
        else:
            high = middle - 1
    return ordered[:low], len(ordered) - low


def _frame_bytes(inst_ids: Sequence[str], channels: Sequence[str]) -> int:
    """一条订阅帧的真实字节数；按更长的 `unsubscribe` 量，退订帧也不会超限。"""

    return len(json.dumps(_frame("unsubscribe", inst_ids, channels)).encode())


_TICKER_PATH = "/api/v5/market/ticker"
_MARK_PRICE_PATH = "/api/v5/public/mark-price"
_INDEX_TICKERS_PATH = "/api/v5/market/index-tickers"

StatusCallback = Callable[[bool, str], None]


@dataclass(frozen=True, slots=True)
class CandleShape:
    """一根 K 线的推送形态：周期、开盘边界与已解析的价格。

    `confirm` 只有两种取值：上游 `confirm=1` 表示这根已经收盘，`0` 表示还在变动。
    只有已收盘的 K 线才是事实，未收盘的由推送层丢弃。
    """

    bar: str
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    confirm: bool


@dataclass(frozen=True, slots=True)
class MarketPush:
    """一条行情推送：上游频道、标的与数据行；K 线另外带已解析的形态。"""

    channel: str
    inst_id: str
    row: dict[str, Any]
    candle: CandleShape | None = None


class _Seen:
    """按 `(频道, 标的, 时间戳, 收盘标记)` 去重的滑动窗口。

    收盘标记参与键值：K 线频道在同一个开盘时间上会先推未收盘、再推已收盘，只用
    `(频道, 标的, 时间戳)` 会把收盘那根当成重放丢掉。行情频道的收盘标记为空，键值
    与之前等价。
    """

    def __init__(self, window: int = DEDUPE_WINDOW) -> None:
        if window < 1:
            raise ValueError("去重窗口必须为正整数")
        self._order: deque[tuple[str, str, str, str]] = deque(maxlen=window)
        self._seen: set[tuple[str, str, str, str]] = set()

    def accept(self, key: tuple[str, str, str, str]) -> bool:
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
    订阅哪些频道由 `channels` 决定：行情用默认的三个，K 线用 `candle_channel(bar)`
    并连业务地址。同一个标的在每个频道各订阅一次，`set_instruments` 按请求长度上限
    截断（见 `fit_subscription`），跳过的数量可以读 `skipped`。
    """

    def __init__(
        self,
        *,
        url: str = DEFAULT_PUBLIC_WS_URL,
        channels: Sequence[str] = DEFAULT_PUBLIC_CHANNELS,
        connect: Callable[..., Any] = ws_connect,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_attempts: int = MAX_RECONNECT_ATTEMPTS,
        backoff_seconds: float = RECONNECT_BASE_SECONDS,
        dedupe_window: int = DEDUPE_WINDOW,
        on_status: StatusCallback | None = None,
    ) -> None:
        self._url = url
        self._channels = tuple(dict.fromkeys(channels))
        self._connect = connect
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._deduper = _Seen(dedupe_window)
        self._on_status = on_status
        self._subscribed: tuple[str, ...] = ()
        self._instruments: set[str] = set()
        self._skipped = 0
        self._changed = asyncio.Event()

    @property
    def subscriptions(self) -> tuple[str, ...]:
        """已经提交给上游的标的（按优先级截断后的结果）。"""

        return self._subscribed

    @property
    def skipped(self) -> int:
        """因为一次订阅请求装不下而没有提交的标的数量。"""

        return self._skipped

    def set_instruments(self, inst_ids: Iterable[str]) -> None:
        """替换订阅集合；连接中会立即增删订阅，重连时按这个集合重新订阅。

        集合按调用方给的顺序装入请求，超出行长上限的标的从尾部跳过；跳过数量记在
        `skipped` 上，由推送层放进健康状态，不静默丢弃。
        """

        kept, skipped = fit_subscription(inst_ids, self._channels)
        if kept != self._subscribed:
            logger.info(
                "上游订阅已更新: channels=%s 标的=%d 跳过=%d",
                ",".join(self._channels),
                len(kept),
                skipped,
            )
        elif skipped:
            logger.warning("上游订阅超出行长上限: 跳过 %d 个标的", skipped)
        self._subscribed = kept
        self._instruments = set(kept)
        self._skipped = skipped
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
                            key = (
                                push.channel,
                                push.inst_id,
                                str(push.row.get("ts") or ""),
                                str(push.row.get("confirm") or ""),
                            )
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
            await socket.send(json.dumps(_frame("subscribe", sorted(added), self._channels)))
        if removed:
            await socket.send(json.dumps(_frame("unsubscribe", sorted(removed), self._channels)))

    def _notify(self, connected: bool, error: str) -> None:
        if self._on_status is not None:
            self._on_status(connected, error)


def _frame(operation: str, inst_ids: Iterable[str], channels: Sequence[str]) -> dict[str, Any]:
    """一条订阅帧：每个标的在自己支持的频道上各一个参数。"""

    return {
        "op": operation,
        "args": [
            {"channel": channel, "instId": inst_id}
            for inst_id in inst_ids
            for channel in _channels_for(inst_id, channels)
        ],
    }


def _channels_for(inst_id: str, channels: Sequence[str]) -> tuple[str, ...]:
    """这个标的能订的频道。

    `index-tickers` 只接受指数标识，也就是现货标识的写法（`BTC-USDT`、
    `XAAPL-USDT`）；永续标识（`AAPL-USDT-SWAP`）没有对应的指数，订了会被上游以
    `60018` / `51001`（`Instrument ID ... doesn't exist`）逐条拒绝，日志里刷屏而
    永远没有推送。干脆不订：永续的指数价本来就要按它的现货配对去取。
    """

    if inst_id.endswith(SWAP_INST_SUFFIX):
        return tuple(channel for channel in channels if channel != INDEX_TICKERS_CHANNEL)
    return tuple(channels)


def _parse_push(raw: str | bytes) -> list[MarketPush]:
    try:
        message = json.loads(raw)
    except ValueError as exc:
        raise ExchangeError("公共推送不是合法 JSON") from exc
    if not isinstance(message, dict):
        raise ExchangeError("公共推送结构异常")
    if message.get("event") == "error":
        # 上游对某个频道或标的的拒绝必须留下痕迹：静默丢弃会让人误以为订阅成功。
        logger.warning(
            "上游拒绝订阅或推送报错: code=%s msg=%s",
            message.get("code"),
            message.get("msg"),
        )
        return []
    arg = message.get("arg")
    channel = str(arg.get("channel") or "") if isinstance(arg, dict) else ""
    arg_inst_id = str(arg.get("instId") or "") if isinstance(arg, dict) else ""
    data = message.get("data")
    if not isinstance(data, list):
        return []
    pushes: list[MarketPush] = []
    for row in data:
        if isinstance(row, dict):
            inst_id = str(row.get("instId") or "")
            if inst_id:
                pushes.append(MarketPush(channel=channel, inst_id=inst_id, row=row))
            continue
        # K 线频道的推送是定长数组，标的只在 `arg` 里；其余频道是对象且自带 instId。
        if isinstance(row, list) and channel.startswith("candle") and arg_inst_id:
            candle = _candle_shape(channel, row)
            if candle is not None:
                pushes.append(
                    MarketPush(
                        channel=channel,
                        inst_id=arg_inst_id,
                        row=_candle_row(row),
                        candle=candle,
                    )
                )
    return pushes


def _candle_row(row: Sequence[Any]) -> dict[str, Any]:
    """K 线数组 → 去重与日志用的行：`ts` 与 `confirm` 与行情频道同名。"""

    return {"ts": row[0], "confirm": row[8]}


def _candle_shape(channel: str, row: Sequence[Any]) -> CandleShape | None:
    """一根 K 线数组 → 结构化形态；列数或价格不合规时返回 `None`。"""

    if len(row) < 9:
        return None
    try:
        return CandleShape(
            bar=from_okx_bar(channel[len("candle") :]),
            open_time=utc_from_millis(row[0]),
            open=Decimal(row[1]),
            high=Decimal(row[2]),
            low=Decimal(row[3]),
            close=Decimal(row[4]),
            volume=Decimal(row[5]),
            confirm=str(row[8]) == "1",
        )
    except (InvalidOperation, TypeError, ValueError):
        return None


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

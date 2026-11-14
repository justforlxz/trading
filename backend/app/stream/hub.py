"""浏览器推送订阅管理：聚合 OKX 行情与私有快照，按订阅分发。

单进程部署没有消息队列与独立 worker：一个 `StreamHub` 挂在应用生命周期内，持有
所有浏览器连接与上游连接。上游连接按需启动——只有第一个浏览器订阅行情或私有频道
时才连 OKX，没有订阅就不产生后台网络请求。

三条边界：

- 浏览器只收到自己订阅的标的；同一标的的高频行情按 1 秒窗口合并，只推窗口内最后
  一条。
- 私有频道先按 B2 的快照结构解析、写库，再推送；写库失败只记录错误，不阻断推送。
- 任何事件都不包含上游凭据或原始应答。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from app.config import get_settings
from app.core import (
    AccountSnapshot,
    Clock,
    ExchangePosition,
    SystemClock,
    ValidationError,
    utc_from_millis,
)
from app.exchange import (
    MarketPush,
    OkxPublicWebSocket,
    OkxWebSocket,
    load_quote_snapshot,
    parse_account_snapshot_row,
    parse_exchange_position_row,
)
from app.positions import (
    DEFAULT_ACCOUNT_ID,
    AccountSyncView,
    AccountView,
    ExchangePositionsView,
    ExchangePositionView,
    account_summary,
    exchange_position_view_from_snapshot,
    exchange_positions,
    record_exchange_snapshot,
    sync_account,
)

__all__ = [
    "EVENT_TYPES",
    "PRIVATE_CHANNELS",
    "StreamClient",
    "StreamHub",
]

logger = logging.getLogger(__name__)

#: 私有频道只订阅账户与持仓；订单、成交推送不属于 v6。
PRIVATE_CHANNELS: tuple[dict[str, str], ...] = (
    {"channel": "account"},
    {"channel": "positions"},
)

#: 浏览器契约里的事件类型；B4 负责前三类，其余由对应业务包后续发布。
EVENT_TYPES: frozenset[str] = frozenset(
    {
        "market.quote.updated",
        "account.snapshot.updated",
        "position.updated",
        "alert.created",
        "alert.updated",
        "activity.created",
        "strategy.signal.created",
        "backtest.status.updated",
        "data_source.status.updated",
    }
)

PUBLIC_DATASET = "public_ws"
PRIVATE_DATASET = "private_ws"
SOURCE_WS = "okx_ws"
SOURCE_REST = "okx_rest"
ACCOUNT_CURRENCY = "USDT"

#: 上游频道 → (事件字段, 上游价格字段)。
_QUOTE_FIELDS: dict[str, tuple[str, str]] = {
    "tickers": ("last", "last"),
    "mark-price": ("mark", "markPx"),
    "index-tickers": ("index", "idxPx"),
}


@dataclass
class StreamClient:
    """一个浏览器连接：发送函数与它关心的标的/频道。"""

    id: str
    send: Callable[[dict[str, Any]], None]
    quotes: set[str] = field(default_factory=set)
    account: bool = False
    positions: bool = False

    def wants(self, inst_id: str) -> bool:
        return inst_id in self.quotes


@dataclass
class _QuoteState:
    """一个标的的已合并行情：每个价格字段独立记录上游时间戳与最近来源。"""

    values: dict[str, Decimal] = field(default_factory=dict)
    timestamps: dict[str, datetime] = field(default_factory=dict)
    source: str | None = None

    def apply(
        self,
        field_name: str,
        value: Any,
        moment: datetime | None,
        *,
        source: str,
    ) -> None:
        parsed = _decimal_or_none(value)
        if parsed is None:
            return
        self.values[field_name] = parsed
        if moment is not None:
            self.timestamps[field_name] = moment
        self.source = source

    def apply_if_newer(
        self,
        field_name: str,
        value: Any,
        moment: datetime | None,
        *,
        source: str,
    ) -> None:
        """只接受不早于现有值的快照：REST 对账不能把更新的推送值盖回旧值。"""

        existing = self.timestamps.get(field_name)
        if existing is not None and moment is not None and moment < existing:
            return
        self.apply(field_name, value, moment, source=source)

    def as_of(self) -> datetime | None:
        return max(self.timestamps.values()) if self.timestamps else None

    def payload(self, *, source: str, snapshot: bool) -> dict[str, Any]:
        return {
            "last": _decimal_text(self.values.get("last")),
            "mark": _decimal_text(self.values.get("mark")),
            "index": _decimal_text(self.values.get("index")),
            "source": source,
            "stale": False,
            "snapshot": snapshot,
        }


@dataclass(frozen=True)
class _QuoteUpdate:
    inst_id: str
    data: dict[str, Any]
    as_of: datetime | None


@dataclass
class _SourceStatus:
    provider: str
    dataset: str
    connected: bool = False
    ever_connected: bool = False
    last_message_at: datetime | None = None
    last_success_at: datetime | None = None
    reconnect_count: int = 0
    last_error: str | None = None


class _QuoteBatcher:
    """同一标的的行情按固定窗口合并：窗口内只保留最后一条。"""

    def __init__(self, interval: float, publish: Callable[[_QuoteUpdate], None]) -> None:
        if interval <= 0:
            raise ValueError("节流窗口必须大于 0")
        self._interval = interval
        self._publish = publish
        self._pending: dict[str, _QuoteUpdate] = {}
        self._timers: dict[str, asyncio.Task[None]] = {}

    def update(self, update: _QuoteUpdate) -> None:
        self._pending[update.inst_id] = update
        if update.inst_id not in self._timers:
            self._timers[update.inst_id] = asyncio.create_task(self._flush(update.inst_id))

    async def _flush(self, inst_id: str) -> None:
        await asyncio.sleep(self._interval)
        self._timers.pop(inst_id, None)
        update = self._pending.pop(inst_id, None)
        if update is not None:
            self._publish(update)

    async def close(self) -> None:
        tasks = list(self._timers.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._timers.clear()
        self._pending.clear()


class StreamHub:
    """浏览器订阅与上游连接的唯一管理者。"""

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        quote_interval: float = 1.0,
        quote_loader: Callable[[Sequence[str]], list[dict[str, Any]]] | None = None,
        account_loader: Callable[[], AccountView] = account_summary,
        positions_loader: Callable[[], ExchangePositionsView] = exchange_positions,
        persist_snapshot: Callable[..., AccountView | None] = record_exchange_snapshot,
        account_sync: Callable[[], AccountSyncView] = sync_account,
        public_factory: Callable[[Callable[[bool, str], None]], Any] | None = None,
        private_factory: Callable[[Callable[[bool, str], None]], Any] | None = None,
        credentials_configured: Callable[[], bool] | None = None,
    ) -> None:
        self._clock = clock or SystemClock()
        self._quote_loader = quote_loader or load_quote_snapshot
        self._account_loader = account_loader
        self._positions_loader = positions_loader
        self._persist_snapshot = persist_snapshot
        self._account_sync = account_sync
        self._public_factory = public_factory or (
            lambda on_status: OkxPublicWebSocket(on_status=on_status)
        )
        self._private_factory = private_factory or (
            lambda on_status: OkxWebSocket(channels=PRIVATE_CHANNELS, on_status=on_status)
        )
        self._credentials_configured = credentials_configured or _credentials_configured

        self._clients: dict[str, StreamClient] = {}
        self._quotes: dict[str, _QuoteState] = {}
        self._last_quote: dict[str, tuple[Any, Any, Any]] = {}
        self._last_account: dict[str, Any] | None = None
        self._last_positions: dict[str, dict[str, Any]] = {}
        self._positions: dict[str, ExchangePosition] = {}
        self._positions_loaded = False
        self._account_details: dict[str, dict[str, Any]] = {}
        self._account_captured_at: datetime | None = None
        self._status: dict[str, _SourceStatus] = {
            PUBLIC_DATASET: _SourceStatus("okx", PUBLIC_DATASET),
            PRIVATE_DATASET: _SourceStatus("okx", PRIVATE_DATASET),
        }
        self._public_client: Any | None = None
        self._private_client: Any | None = None
        self._public_task: asyncio.Task[None] | None = None
        self._private_task: asyncio.Task[None] | None = None
        self._reconcile_tasks: set[asyncio.Task[None]] = set()
        self._batcher = _QuoteBatcher(quote_interval, self._publish_quote)

    # ---------------------------------------------------------------- 浏览器连接

    def register(self, send: Callable[[dict[str, Any]], None]) -> StreamClient:
        client = StreamClient(id=uuid4().hex, send=send)
        self._clients[client.id] = client
        return client

    def unregister(self, client: StreamClient) -> None:
        self._clients.pop(client.id, None)
        self._sync_upstreams()

    async def handle(self, client: StreamClient, message: Any) -> None:
        """处理一条浏览器订阅消息；格式错误只回错误事件，不关闭连接。"""

        if not isinstance(message, dict) or message.get("action") != "subscribe":
            self._send_error(client, "只支持 action=subscribe")
            return
        topics = message.get("topics")
        if not isinstance(topics, list):
            self._send_error(client, "topics 必须是数组")
            return
        await self.subscribe(client, topics)

    async def subscribe(self, client: StreamClient, topics: Iterable[Any]) -> None:
        """登记订阅并补发初始快照；同一标的高频更新由 `_batcher` 合并。"""

        new_quotes: set[str] = set()
        ask_account = False
        ask_positions = False
        for topic in topics:
            if not isinstance(topic, dict):
                self._send_error(client, "订阅项必须是对象")
                continue
            kind = topic.get("type")
            if kind == "quote":
                inst_ids = topic.get("inst_ids")
                if not isinstance(inst_ids, list) or not all(
                    isinstance(item, str) and item for item in inst_ids
                ):
                    self._send_error(client, "quote 订阅需要非空的 inst_ids 数组")
                    continue
                new_quotes.update(item for item in inst_ids if item not in client.quotes)
                client.quotes.update(inst_ids)
            elif kind == "account":
                ask_account = not client.account
                client.account = True
            elif kind == "positions":
                ask_positions = not client.positions
                client.positions = True
            else:
                self._send_error(client, f"不支持的订阅类型 {kind!r}")

        self._sync_upstreams()
        if new_quotes:
            self._send_status(client, PUBLIC_DATASET)
            await self._send_quote_initial(client, new_quotes)
        if ask_account or ask_positions:
            self._send_status(client, PRIVATE_DATASET)
        if ask_account:
            await self._send_account_initial(client)
        if ask_positions:
            await self._send_positions_initial(client)

    # ------------------------------------------------------------------ 上游连接

    def _sync_upstreams(self) -> None:
        wanted_quotes = sorted(
            {inst for client in self._clients.values() for inst in client.quotes}
        )
        if wanted_quotes:
            if self._public_client is None:
                self._public_client = self._public_factory(self._status_callback(PUBLIC_DATASET))
                self._public_task = asyncio.create_task(
                    self._run_public(self._public_client), name="trading-stream-public"
                )
            self._public_client.set_instruments(wanted_quotes)
        elif self._public_task is not None:
            self._public_task.cancel()
            self._public_task = None
            self._public_client = None

        wanted_private = any(
            client.account or client.positions for client in self._clients.values()
        )
        if wanted_private and self._private_task is None:
            if not self._credentials_configured():
                self._set_status(PRIVATE_DATASET, False, "未配置 OKX 私有凭据")
                return
            self._private_client = self._private_factory(self._status_callback(PRIVATE_DATASET))
            self._private_task = asyncio.create_task(
                self._run_private(self._private_client), name="trading-stream-private"
            )
        elif not wanted_private and self._private_task is not None:
            self._private_task.cancel()
            self._private_task = None
            self._private_client = None

    async def _run_public(self, client: Any) -> None:
        try:
            async for push in client.messages():
                self._handle_market(push)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # 上游放弃重连后把原因留在状态里
            logger.exception("公共行情推送停止")
            self._set_status(PUBLIC_DATASET, False, str(exc))

    async def _run_private(self, client: Any) -> None:
        try:
            async for channel, rows in client.channel_messages():
                for row in rows:
                    await self._handle_private(channel, row)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("私有推送停止")
            self._set_status(PRIVATE_DATASET, False, str(exc))

    def _status_callback(self, dataset: str) -> Callable[[bool, str], None]:
        return lambda connected, error: self._set_status(dataset, connected, error)

    def _set_status(self, dataset: str, connected: bool, error: str) -> None:
        status = self._status[dataset]
        now = self._clock.now()
        if connected:
            if status.ever_connected:
                status.reconnect_count += 1
                self._schedule_reconcile(dataset)
            status.ever_connected = True
            status.connected = True
            status.last_error = None
            status.last_success_at = now
        else:
            status.connected = False
            if error:
                status.last_error = error
        self._broadcast_status(dataset)

    def _schedule_reconcile(self, dataset: str) -> None:
        if dataset == PUBLIC_DATASET:
            task = asyncio.create_task(
                self._reconcile_quotes(), name="trading-stream-quote-reconcile"
            )
        else:
            task = asyncio.create_task(
                self._reconcile_private(), name="trading-stream-private-reconcile"
            )
        self._reconcile_tasks.add(task)
        task.add_done_callback(self._reconcile_tasks.discard)

    async def _reconcile_quotes(self) -> None:
        """重连后用 REST 对账一次；值没变就不重复推送。"""

        inst_ids = sorted({inst for client in self._clients.values() for inst in client.quotes})
        if not inst_ids:
            return
        try:
            rows = await asyncio.to_thread(self._quote_loader, inst_ids)
        except Exception:
            logger.exception("行情重连对账失败")
            return
        for row in rows:
            inst_id = str(row.get("inst_id") or "")
            if inst_id:
                self._apply_snapshot_row(inst_id, row, snapshot=True)

    async def _reconcile_private(self) -> None:
        """私有频道重连后用 REST 同步一次，修复断线期间漏掉的账户与持仓变化。"""

        try:
            result = await asyncio.to_thread(self._account_sync)
        except Exception:
            logger.exception("私有频道重连对账失败")
            return
        if result.summary.captured_at is not None:
            self._account_captured_at = result.summary.captured_at
        await self._reload_positions()
        await self._emit_account_view(result.summary, snapshot=True, source=SOURCE_REST)

    # -------------------------------------------------------------- 行情事件处理

    def _handle_market(self, push: MarketPush) -> None:
        mapping = _QUOTE_FIELDS.get(push.channel)
        if mapping is None:
            return
        field_name, source_field = mapping
        status = self._status[PUBLIC_DATASET]
        now = self._clock.now()
        status.last_message_at = now
        status.last_success_at = now
        self._quotes.setdefault(push.inst_id, _QuoteState()).apply(
            field_name,
            push.row.get(source_field),
            _row_time(push.row),
            source=SOURCE_WS,
        )
        self._queue_quote(push.inst_id, snapshot=False, source=SOURCE_WS)

    def _apply_snapshot_row(
        self,
        inst_id: str,
        row: dict[str, Any],
        *,
        snapshot: bool,
    ) -> None:
        state = self._quotes.setdefault(inst_id, _QuoteState())
        moment = _row_time(row)
        for field_name, row_field in (("last", "last"), ("mark", "mark"), ("index", "index")):
            if row_field in row:
                state.apply_if_newer(field_name, row.get(row_field), moment, source=SOURCE_REST)
        self._queue_quote(inst_id, snapshot=snapshot, source=SOURCE_REST)

    def _queue_quote(self, inst_id: str, *, snapshot: bool, source: str) -> None:
        state = self._quotes.get(inst_id)
        if state is None or not state.values:
            return
        update = _QuoteUpdate(
            inst_id=inst_id,
            data=state.payload(source=state.source or source, snapshot=snapshot),
            as_of=state.as_of(),
        )
        self._batcher.update(update)

    def _publish_quote(self, update: _QuoteUpdate) -> None:
        signature = _signature(update.data)
        if self._last_quote.get(update.inst_id) == signature:
            return
        self._last_quote[update.inst_id] = signature
        data = {"inst_id": update.inst_id, **update.data}
        self._broadcast_envelope(
            "market.quote.updated",
            data,
            as_of=update.as_of,
            predicate=lambda client: client.wants(update.inst_id),
        )

    async def _send_quote_initial(self, client: StreamClient, inst_ids: Iterable[str]) -> None:
        cached: dict[str, tuple[Any, Any, Any]] = {}
        for inst_id in inst_ids:
            state = self._quotes.get(inst_id)
            if state is None or not state.values:
                continue
            data = {
                "inst_id": inst_id,
                **state.payload(source=state.source or SOURCE_WS, snapshot=True),
            }
            self._send_envelope(client, "market.quote.updated", data, as_of=state.as_of())
            cached[inst_id] = _signature(data)
        try:
            rows = await asyncio.to_thread(self._quote_loader, sorted(inst_ids))
        except Exception:
            logger.exception("初始行情快照加载失败")
            return
        for row in rows:
            inst_id = str(row.get("inst_id") or "")
            if not inst_id:
                continue
            state = self._quotes.setdefault(inst_id, _QuoteState())
            moment = _row_time(row)
            for field_name, row_field in (("last", "last"), ("mark", "mark"), ("index", "index")):
                if row_field in row:
                    state.apply_if_newer(field_name, row.get(row_field), moment, source=SOURCE_REST)
            data = {"inst_id": inst_id, **state.payload(source=SOURCE_REST, snapshot=True)}
            signature = _signature(data)
            if cached.get(inst_id) == signature:
                self._last_quote[inst_id] = signature
                continue
            self._last_quote[inst_id] = signature
            self._broadcast_envelope(
                "market.quote.updated",
                data,
                as_of=state.as_of(),
                predicate=lambda item, inst_id=inst_id: item.wants(inst_id),
            )

    # -------------------------------------------------------------- 私有事件处理

    async def _handle_private(self, channel: str, row: dict[str, Any]) -> None:
        status = self._status[PRIVATE_DATASET]
        status.last_message_at = self._clock.now()
        status.last_success_at = status.last_message_at
        if channel == "account":
            await self._handle_account_row(row)
        elif channel == "positions":
            await self._handle_position_row(row)

    async def _ensure_private_state_loaded(self) -> bool:
        """首次私有推送前补齐当前持仓与账户时刻，避免整批写入时丢掉已有持仓。"""

        if self._positions_loaded:
            return True
        try:
            positions = await asyncio.to_thread(self._positions_loader)
            account = await asyncio.to_thread(self._account_loader)
        except Exception:
            logger.exception("私有持仓状态初始化失败，本次只推送不写库")
            return False
        self._positions = {
            item.pos_id: _exchange_position_from_view(item) for item in positions.items
        }
        if self._account_captured_at is None:
            self._account_captured_at = account.captured_at
        self._positions_loaded = True
        return True

    async def _reload_positions(self) -> None:
        """重连对账后同步内存持仓，下一次推送继续写入同一批账户时刻。"""

        try:
            positions = await asyncio.to_thread(self._positions_loader)
        except Exception:
            logger.exception("私有持仓状态刷新失败")
            return
        self._positions = {
            item.pos_id: _exchange_position_from_view(item) for item in positions.items
        }
        self._positions_loaded = True

    async def _handle_account_row(self, row: dict[str, Any]) -> None:
        loaded = await self._ensure_private_state_loaded()
        try:
            snapshot = parse_account_snapshot_row(
                self._merge_account_details(row),
                currency=ACCOUNT_CURRENCY,
            )
        except Exception:
            logger.exception("账户推送解析失败，跳过该行")
            return
        captured_at = _row_time(row) or self._clock.now()
        self._account_captured_at = captured_at
        await self._persist(
            captured_at=captured_at,
            snapshot=snapshot,
            positions=tuple(self._positions.values()) if loaded else None,
            source=SOURCE_WS,
        )
        data = _account_payload(snapshot, captured_at=captured_at, source=SOURCE_WS)
        if self._last_account == data:
            return
        self._last_account = data
        self._broadcast_envelope(
            "account.snapshot.updated",
            data,
            as_of=captured_at,
            predicate=lambda client: client.account,
        )

    def _merge_account_details(self, row: dict[str, Any]) -> dict[str, Any]:
        """把推送里的币种明细并入缓存，返回带完整 `details` 的账户行。

        OKX 的 `event_update` 只下发发生变化的币种；直接用这一条重算整份账户快照
        会让其他币种的明细丢失，现金余额被算成 0。这里按币种合并，只覆盖推送中
        出现且非空的字段，再用合并后的明细交给解析函数。
        """

        details = row.get("details")
        if isinstance(details, list):
            for item in details:
                if not isinstance(item, dict):
                    continue
                currency = str(item.get("ccy") or "")
                if not currency:
                    continue
                merged = self._account_details.get(currency, {"ccy": currency})
                for key, value in item.items():
                    if value is None or value == "":
                        continue
                    merged[key] = value
                self._account_details[currency] = merged
        if not self._account_details:
            return row
        return {**row, "details": list(self._account_details.values())}

    async def _handle_position_row(self, row: dict[str, Any]) -> None:
        loaded = await self._ensure_private_state_loaded()
        try:
            item = parse_exchange_position_row(row)
        except Exception:
            logger.exception("持仓推送解析失败，跳过该行")
            return
        captured_at = self._account_captured_at or _row_time(row) or self._clock.now()
        if loaded:
            if item.size == 0:
                self._positions.pop(item.pos_id, None)
            else:
                self._positions[item.pos_id] = item
            await self._persist(
                captured_at=captured_at,
                snapshot=None,
                positions=tuple(self._positions.values()),
                source=SOURCE_WS,
            )
        payload = _position_payload(exchange_position_view_from_snapshot(item))
        if self._last_positions.get(item.pos_id) == payload:
            return
        self._last_positions[item.pos_id] = payload
        self._broadcast_envelope(
            "position.updated",
            payload,
            as_of=captured_at,
            predicate=lambda client: client.positions,
        )

    async def _persist(
        self,
        *,
        captured_at: datetime,
        snapshot: AccountSnapshot | None,
        positions: Sequence[ExchangePosition] | None,
        source: str,
    ) -> None:
        """写库失败只记录错误：推送的事实来自同一份已解析快照，不应该被库故障吞掉。"""

        try:
            await asyncio.to_thread(
                self._persist_snapshot,
                captured_at=captured_at,
                source=source,
                snapshot=snapshot,
                positions=positions,
            )
        except Exception:
            logger.exception("推送快照写库失败")

    async def _send_account_initial(self, client: StreamClient) -> None:
        view = await asyncio.to_thread(self._account_loader)
        if view.captured_at is None:
            return
        data = _account_view_payload(view)
        self._send_envelope(
            client,
            "account.snapshot.updated",
            data,
            as_of=view.captured_at,
            snapshot=True,
        )

    async def _send_positions_initial(self, client: StreamClient) -> None:
        view = await asyncio.to_thread(self._positions_loader)
        if view.as_of is None:
            return
        for item in view.items:
            self._send_envelope(
                client,
                "position.updated",
                _position_payload(item),
                as_of=view.as_of,
                snapshot=True,
            )

    async def _emit_account_view(
        self,
        view: AccountView,
        *,
        snapshot: bool,
        source: str,
    ) -> None:
        if view.captured_at is None:
            return
        data = _account_view_payload(view)
        self._broadcast_envelope(
            "account.snapshot.updated",
            data,
            as_of=view.captured_at,
            snapshot=snapshot,
            predicate=lambda client: client.account,
        )
        if source == SOURCE_REST:
            positions = await asyncio.to_thread(self._positions_loader)
            for item in positions.items:
                self._broadcast_envelope(
                    "position.updated",
                    _position_payload(item),
                    as_of=positions.as_of,
                    snapshot=snapshot,
                    predicate=lambda client: client.positions,
                )

    # -------------------------------------------------------------------- 消息发送

    def _send_error(self, client: StreamClient, message: str) -> None:
        self._send_envelope(
            client,
            "stream.error",
            {"message": message},
            as_of=None,
        )

    def _send_status(self, client: StreamClient, dataset: str) -> None:
        self._send_envelope(
            client,
            "data_source.status.updated",
            self._status_payload(dataset),
            as_of=None,
        )

    def _broadcast_status(self, dataset: str) -> None:
        if dataset == PUBLIC_DATASET:
            predicate = lambda client: bool(client.quotes)  # noqa: E731
        else:
            predicate = lambda client: client.account or client.positions  # noqa: E731
        self._broadcast_envelope(
            "data_source.status.updated",
            self._status_payload(dataset),
            as_of=None,
            predicate=predicate,
        )

    def _status_payload(self, dataset: str) -> dict[str, Any]:
        status = self._status[dataset]
        return {
            "provider": status.provider,
            "dataset": status.dataset,
            "status": "connected" if status.connected else "disconnected",
            "connected": status.connected,
            "last_message_at": _iso(status.last_message_at),
            "last_success_at": _iso(status.last_success_at),
            "reconnect_count": status.reconnect_count,
            "error": status.last_error,
            "last_error": status.last_error,
        }

    def _broadcast_envelope(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        as_of: datetime | None,
        snapshot: bool = False,
        predicate: Callable[[StreamClient], bool] | None = None,
    ) -> None:
        if snapshot:
            data = {**data, "snapshot": True}
        envelope = _envelope(event_type, data, as_of=as_of, now=self._clock.now())
        for client in list(self._clients.values()):
            if predicate is None or predicate(client):
                self._deliver(client, envelope)

    def _send_envelope(
        self,
        client: StreamClient,
        event_type: str,
        data: dict[str, Any],
        *,
        as_of: datetime | None,
        snapshot: bool = False,
    ) -> None:
        if snapshot:
            data = {**data, "snapshot": True}
        self._deliver(client, _envelope(event_type, data, as_of=as_of, now=self._clock.now()))

    def _deliver(self, client: StreamClient, envelope: dict[str, Any]) -> None:
        try:
            client.send(envelope)
        except Exception:
            logger.exception("推送发送失败，移除客户端 %s", client.id)
            self._clients.pop(client.id, None)

    async def publish(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        as_of: datetime | None = None,
    ) -> None:
        """供提醒、活动、策略、回测等业务包发布低频事件。"""

        if event_type not in EVENT_TYPES:
            raise ValidationError(f"未知推送事件类型 {event_type!r}")
        self._broadcast_envelope(event_type, data, as_of=as_of)

    async def stop(self) -> None:
        """应用退出或测试收尾：取消上游任务与节流定时器。"""

        tasks = [
            task
            for task in (self._public_task, self._private_task, *self._reconcile_tasks)
            if task is not None
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._public_task = None
        self._private_task = None
        self._public_client = None
        self._private_client = None
        await self._batcher.close()


def _envelope(
    event_type: str,
    data: dict[str, Any],
    *,
    as_of: datetime | None,
    now: datetime,
) -> dict[str, Any]:
    return {
        "type": event_type,
        "as_of": _iso(as_of or now),
        "received_at": _iso(now),
        "data": data,
    }


def _exchange_position_from_view(view: ExchangePositionView) -> ExchangePosition:
    """把 B2 的持仓视图还原成写库用的快照，字段一一对应。"""

    return ExchangePosition(
        pos_id=view.pos_id,
        inst_id=view.inst_id,
        pos_side=view.pos_side,
        size=view.size,
        avg_px=view.avg_px,
        mark_px=view.mark_px,
        upl=view.upl,
        upl_ratio=view.upl_ratio,
        lever=view.lever,
        mgn_mode=view.mgn_mode,
        liq_px=view.liq_px,
        margin=view.margin,
    )


def _account_view_payload(view: AccountView) -> dict[str, Any]:
    return {
        "account_id": view.account_id,
        "currency": view.currency,
        "equity": _decimal_text(view.equity),
        "available_equity": _decimal_text(view.available_equity),
        "cash_balance": _decimal_text(view.cash_balance),
        "unrealized_pnl": _decimal_text(view.unrealized_pnl),
        "used_margin": _decimal_text(view.used_margin),
        "available_margin": _decimal_text(view.available_margin),
        "margin_usage_pct": _decimal_text(view.margin_usage_pct),
        "captured_at": _iso(view.captured_at),
        "source": view.source,
    }


def _account_payload(
    snapshot: AccountSnapshot,
    *,
    captured_at: datetime,
    source: str,
) -> dict[str, Any]:
    return {
        "account_id": DEFAULT_ACCOUNT_ID,
        "currency": snapshot.currency,
        "equity": _decimal_text(snapshot.equity),
        "available_equity": _decimal_text(snapshot.available_equity),
        "cash_balance": _decimal_text(snapshot.cash_balance),
        "unrealized_pnl": _decimal_text(snapshot.unrealized_pnl),
        "used_margin": _decimal_text(snapshot.used_margin),
        "available_margin": _decimal_text(snapshot.available_margin),
        "margin_usage_pct": _decimal_text(snapshot.margin_ratio * 100),
        "captured_at": _iso(captured_at),
        "source": source,
    }


def _position_payload(view: ExchangePositionView) -> dict[str, Any]:
    return {
        "pos_id": view.pos_id,
        "inst_id": view.inst_id,
        "display_symbol": view.display_symbol,
        "name": view.name,
        "asset_class": view.asset_class,
        "pos_side": view.pos_side,
        "size": _decimal_text(view.size),
        "avg_px": _decimal_text(view.avg_px),
        "mark_px": _decimal_text(view.mark_px),
        "upl": _decimal_text(view.upl),
        "upl_ratio": _decimal_text(view.upl_ratio),
        "lever": _decimal_text(view.lever),
        "mgn_mode": view.mgn_mode,
        "liq_px": _decimal_text(view.liq_px),
        "margin": _decimal_text(view.margin),
    }


def _signature(data: dict[str, Any]) -> tuple[Any, Any, Any]:
    return data.get("last"), data.get("mark"), data.get("index")


def _row_time(row: dict[str, Any]) -> datetime | None:
    value = row.get("ts") or row.get("uTime")
    if value is None or str(value) == "":
        return None
    try:
        return utc_from_millis(value)
    except (TypeError, ValueError):
        return None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or str(value) == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _credentials_configured() -> bool:
    settings = get_settings()
    return all(
        value.strip()
        for value in (settings.okx_api_key, settings.okx_secret_key, settings.okx_passphrase)
    )

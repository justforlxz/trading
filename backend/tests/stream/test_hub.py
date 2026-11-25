"""浏览器推送：订阅过滤、节流、去重、私有推送与写库失败降级。

上游用空闲的假客户端替代，测试直接调用推送入口驱动事件，不连 OKX、不写数据库。
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, ClassVar

from app.activity import list_activity
from app.db import init_db
from app.exchange import CandleShape, MarketPush
from app.instrument import sync_instruments
from app.positions import ExchangePositionView
from app.stream import StreamHub
from app.stream.hub import CANDLE_DATASET, PRIVATE_CHANNELS, PRIVATE_DATASET
from app.watchlist import WatchRegistry
from tests.factories.instruments import make_swap_ref


class IdlePublic:
    """占位公共客户端：只记录订阅集合，不产生推送。"""

    def __init__(self, _on_status: Any) -> None:
        self.instruments: set[str] = set()

    def set_instruments(self, inst_ids: Any) -> None:
        self.instruments = set(inst_ids)

    async def messages(self):  # type: ignore[no-untyped-def]
        await asyncio.Event().wait()
        yield  # pragma: no cover


def _hub(**overrides: Any) -> StreamHub:
    options = {
        "quote_interval": 0.01,
        "quote_loader": lambda _ids: [],
        "account_loader": lambda: SimpleNamespace(captured_at=None),
        "positions_loader": lambda: SimpleNamespace(items=(), as_of=None),
        "public_factory": IdlePublic,
        # K 线另开一条连接：默认同样用不会连上游、不会推送的占位客户端。
        "candle_bar": "1h",
        "candle_factory": IdlePublic,
        "credentials_configured": lambda: False,
        # 常驻订阅集合默认空：这些用例只关心浏览器订阅；常驻订阅另有专门用例。
        "watch_registry": WatchRegistry(tracked=lambda: []),
    }
    options.update(overrides)
    return StreamHub(**options)


def _quotes(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event["type"] == "market.quote.updated"]


def test_private_channels_subscribe_positions_with_the_swap_instrument_type() -> None:
    """`positions` 频道缺 instType 会被上游拒绝，且订阅范围只有账户与持仓。"""

    assert {item["channel"] for item in PRIVATE_CHANNELS} == {"account", "positions"}
    assert {"channel": "positions", "instType": "SWAP"} in PRIVATE_CHANNELS


def test_two_clients_with_different_instruments_do_not_cross_stream() -> None:
    async def scenario() -> None:
        first_events: list[dict[str, Any]] = []
        second_events: list[dict[str, Any]] = []
        hub = _hub()
        first = hub.register(first_events.append)
        second = hub.register(second_events.append)
        await hub.subscribe(first, [{"type": "quote", "inst_ids": ["XAAPL-USDT"]}])
        await hub.subscribe(second, [{"type": "quote", "inst_ids": ["AAPL-USDT-SWAP"]}])

        hub._handle_market(
            MarketPush(
                "tickers",
                "XAAPL-USDT",
                {"instId": "XAAPL-USDT", "last": "231.42", "ts": "1794284760000"},
            )
        )
        await asyncio.sleep(0.03)
        await hub.stop()

        assert [event["data"]["inst_id"] for event in _quotes(first_events)] == ["XAAPL-USDT"]
        assert _quotes(second_events) == []

    asyncio.run(scenario())


def test_subscribe_pushes_the_initial_rest_snapshot_immediately() -> None:
    async def scenario() -> None:
        events: list[dict[str, Any]] = []
        hub = _hub(
            quote_loader=lambda _ids: [
                {"inst_id": "XAAPL-USDT", "last": "231.42", "ts": 1794284760000}
            ]
        )
        client = hub.register(events.append)

        await hub.subscribe(client, [{"type": "quote", "inst_ids": ["XAAPL-USDT"]}])
        await hub.stop()

        quotes = _quotes(events)
        assert len(quotes) == 1
        assert quotes[0]["data"]["last"] == "231.42"
        assert quotes[0]["data"]["source"] == "okx_rest"
        assert quotes[0]["data"]["snapshot"] is True

    asyncio.run(scenario())


def test_cached_initial_quote_keeps_its_rest_source() -> None:
    async def scenario() -> None:
        hub = _hub(
            quote_loader=lambda _ids: [
                {"inst_id": "XAAPL-USDT", "last": "231.42", "ts": 1794284760000}
            ]
        )
        first = hub.register(lambda _event: None)
        await hub.subscribe(first, [{"type": "quote", "inst_ids": ["XAAPL-USDT"]}])

        second_events: list[dict[str, Any]] = []
        second = hub.register(second_events.append)
        await hub.subscribe(second, [{"type": "quote", "inst_ids": ["XAAPL-USDT"]}])
        await hub.stop()

        quotes = _quotes(second_events)
        assert quotes[0]["data"]["last"] == "231.42"
        assert quotes[0]["data"]["source"] == "okx_rest"
        assert quotes[0]["data"]["snapshot"] is True

    asyncio.run(scenario())


def test_one_hundred_updates_in_a_window_only_push_the_last_value() -> None:
    async def scenario() -> None:
        events: list[dict[str, Any]] = []
        hub = _hub(quote_interval=0.05)
        client = hub.register(events.append)
        await hub.subscribe(client, [{"type": "quote", "inst_ids": ["XAAPL-USDT"]}])

        for value in range(100):
            hub._handle_market(
                MarketPush(
                    "tickers",
                    "XAAPL-USDT",
                    {"instId": "XAAPL-USDT", "last": str(value), "ts": "1794284760000"},
                )
            )
        await asyncio.sleep(0.1)
        await hub.stop()

        quotes = _quotes(events)
        assert len(quotes) == 1
        assert quotes[0]["data"]["last"] == "99"

    asyncio.run(scenario())


def test_the_same_value_is_not_pushed_twice() -> None:
    async def scenario() -> None:
        events: list[dict[str, Any]] = []
        hub = _hub()
        client = hub.register(events.append)
        await hub.subscribe(client, [{"type": "quote", "inst_ids": ["XAAPL-USDT"]}])
        push = MarketPush(
            "tickers",
            "XAAPL-USDT",
            {"instId": "XAAPL-USDT", "last": "231.42", "ts": "1794284760000"},
        )

        hub._handle_market(push)
        await asyncio.sleep(0.03)
        hub._handle_market(push)
        await asyncio.sleep(0.03)
        await hub.stop()

        assert len(_quotes(events)) == 1

    asyncio.run(scenario())


def test_reconnect_reconciles_with_a_rest_snapshot() -> None:
    async def scenario() -> None:
        events: list[dict[str, Any]] = []
        hub = _hub(
            quote_loader=lambda _ids: [
                {"inst_id": "XAAPL-USDT", "last": "232.00", "ts": 1794284761000}
            ],
            watch_registry=WatchRegistry(tracked=lambda: ["XAAPL-USDT"]),
        )
        client = hub.register(events.append)
        client.quotes = {"XAAPL-USDT"}
        hub._status["public_ws"].ever_connected = True

        hub._set_status("public_ws", True, "")
        await asyncio.sleep(0.03)
        await hub.stop()

        quotes = _quotes(events)
        assert len(quotes) == 1
        assert quotes[0]["data"]["last"] == "232"
        assert hub._status["public_ws"].reconnect_count == 1

    asyncio.run(scenario())


def test_status_changes_append_data_source_activity() -> None:
    """数据源断线与重连各写一条活动；重复的同一状态不重复写。"""

    init_db()

    async def scenario() -> None:
        hub = _hub()
        hub._set_status("public_ws", True, "")
        hub._set_status("public_ws", False, "连接中断")
        hub._set_status("public_ws", False, "连接中断")
        hub._set_status("public_ws", True, "")
        await hub.stop()

    asyncio.run(scenario())

    events, _ = list_activity(event_type="data_source.disconnected")
    assert [event.object_id for event in events] == ["okx:public_ws"]
    assert events[0].payload["error"] == "连接中断"
    connected, _ = list_activity(event_type="data_source.connected")
    reconnected, _ = list_activity(event_type="data_source.reconnected")
    assert len(connected) == 1
    assert [event.summary for event in reconnected] == ["行情数据源已重连"]


def test_status_subscription_reports_both_data_sources_without_starting_upstreams() -> None:
    """只订阅状态时立即回公共与私有通道状态，但不启动行情上游连接。"""

    async def scenario() -> None:
        events: list[dict[str, Any]] = []
        hub = _hub()
        client = hub.register(events.append)

        await hub.subscribe(client, [{"type": "status"}])
        statuses = [e for e in events if e["type"] == "data_source.status.updated"]

        assert {event["data"]["dataset"] for event in statuses} == {"public_ws", "private_ws"}
        assert all(event["data"]["connected"] is False for event in statuses)
        assert hub._public_task is None
        await hub.stop()

    asyncio.run(scenario())


def test_status_subscription_receives_later_connection_changes() -> None:
    """状态订阅不是一次性快照：上游连接变化后继续推送。"""

    async def scenario() -> None:
        events: list[dict[str, Any]] = []
        hub = _hub()
        client = hub.register(events.append)
        await hub.subscribe(client, [{"type": "status"}])
        events.clear()

        hub._set_status("public_ws", True, "")
        statuses = [e for e in events if e["type"] == "data_source.status.updated"]

        assert len(statuses) == 1
        assert statuses[0]["data"]["dataset"] == "public_ws"
        assert statuses[0]["data"]["connected"] is True
        await hub.stop()

    asyncio.run(scenario())


def test_private_push_is_delivered_even_when_the_database_write_fails() -> None:
    async def scenario() -> None:
        events: list[dict[str, Any]] = []
        hub = _hub(persist_snapshot=_fail_persist)
        client = hub.register(events.append)
        client.account = True

        await hub._handle_account_row(_account_row(uTime="1794284760000"))
        await hub.stop()

        accounts = [e for e in events if e["type"] == "account.snapshot.updated"]
        assert len(accounts) == 1
        assert accounts[0]["data"]["equity"] == "100"
        assert accounts[0]["data"]["cash_balance"] == "50"
        assert accounts[0]["data"]["captured_at"] == "2026-11-10T04:26:00Z"

    asyncio.run(scenario())


def test_private_positions_are_delivered_with_the_same_fields_as_the_api_item(
    client: Any,
) -> None:
    sync_instruments([make_swap_ref()])

    async def scenario() -> None:
        events: list[dict[str, Any]] = []
        hub = _hub(persist_snapshot=_no_persist)
        client = hub.register(events.append)
        client.positions = True

        await hub._handle_position_row(
            {
                "instId": "AAPL-USDT-SWAP",
                "posId": "123",
                "pos": "2",
                "posSide": "long",
                "avgPx": "100",
                "markPx": "101",
                "upl": "2",
                "uplRatio": "0.01",
                "lever": "3",
                "mgnMode": "cross",
                "liqPx": "80",
                "margin": "60",
                "uTime": "1794284760000",
            }
        )
        await hub.stop()

        updates = [e for e in events if e["type"] == "position.updated"]
        assert len(updates) == 1
        data = updates[0]["data"]
        assert data["inst_id"] == "AAPL-USDT-SWAP"
        assert data["pos_id"] == "123"
        assert data["size"] == "2"
        assert data["avg_px"] == "100"
        assert data["mark_px"] == "101"

    asyncio.run(scenario())


class TwoRowPrivate:
    """一次封包带回两行账户数据：验证推送层按行展开。"""

    def __init__(self, _on_status: Any) -> None:
        pass

    async def channel_messages(self):  # type: ignore[no-untyped-def]
        yield (
            "account",
            [
                _account_row(uTime="1794284760000"),
                _account_row(
                    uTime="1794284770000",
                    totalEq="200",
                    availEq="180",
                    details=[
                        {"ccy": "USDT", "eq": "200", "availEq": "180", "cashBal": "150", "upl": "0"}
                    ],
                ),
            ],
        )


def test_private_channel_packet_handles_every_row() -> None:
    async def scenario() -> None:
        events: list[dict[str, Any]] = []
        hub = _hub(
            account_loader=lambda: SimpleNamespace(captured_at=None),
            credentials_configured=lambda: True,
            private_factory=TwoRowPrivate,
            persist_snapshot=_no_persist,
        )
        client = hub.register(events.append)

        await hub.subscribe(client, [{"type": "account"}])
        await asyncio.sleep(0.03)
        await hub.stop()

        accounts = [e for e in events if e["type"] == "account.snapshot.updated"]
        assert [event["data"]["equity"] for event in accounts] == ["100", "200"]

    asyncio.run(scenario())


def _account_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "totalEq": "100",
        "availEq": "80",
        "imr": "20",
        "upl": "1",
        "uTime": "1794284760000",
        "details": [
            {"ccy": "BTC", "eq": "1", "availEq": "1", "cashBal": "1", "upl": "0"},
            {"ccy": "USDT", "eq": "100", "availEq": "80", "cashBal": "50", "upl": "2"},
        ],
    }
    row.update(overrides)
    return row


def _position_view(pos_id: str, size: str, *, mark_px: str = "101") -> ExchangePositionView:
    return ExchangePositionView(
        pos_id=pos_id,
        inst_id="AAPL-USDT-SWAP",
        display_symbol="AAPL",
        name="AAPL-USDT-SWAP",
        asset_class="us_equity",
        pos_side="long",
        size=Decimal(size),
        avg_px=Decimal("100"),
        mark_px=Decimal(mark_px),
        upl=None,
        upl_ratio=None,
        lever=None,
        mgn_mode=None,
        liq_px=None,
        margin=None,
        stop_px=None,
        # 推送视图不携带止损：如实标成「未取到」，不是「没挂」。
        stop_status="unavailable",
    )


def test_position_updates_keep_all_positions_in_the_account_snapshot_batch(client: Any) -> None:
    sync_instruments([make_swap_ref()])
    account_at = datetime(2026, 11, 10, 4, 26, tzinfo=UTC)
    loaded_at = datetime(2026, 11, 9, 0, 0, tzinfo=UTC)
    calls: list[dict[str, Any]] = []

    def record(**kwargs: Any) -> None:
        calls.append(kwargs)

    async def scenario() -> None:
        events: list[dict[str, Any]] = []
        hub = _hub(
            account_loader=lambda: SimpleNamespace(captured_at=loaded_at),
            positions_loader=lambda: SimpleNamespace(
                items=(_position_view("1", "2"), _position_view("2", "3")),
                as_of=account_at,
            ),
            persist_snapshot=record,
        )
        client = hub.register(events.append)
        client.positions = True

        await hub._handle_account_row(_account_row(uTime="1794284760000"))
        await hub._handle_position_row(
            {
                "instId": "AAPL-USDT-SWAP",
                "posId": "1",
                "pos": "5",
                "posSide": "long",
                "avgPx": "100",
                "markPx": "102",
                "uTime": "1794284770000",
            }
        )
        await hub._handle_position_row(
            {
                "instId": "AAPL-USDT-SWAP",
                "posId": "2",
                "pos": "0",
                "posSide": "long",
                "avgPx": "100",
                "uTime": "1794284780000",
            }
        )
        await hub.stop()

        assert calls[0]["captured_at"] == account_at
        assert calls[0]["snapshot"] is not None
        assert {item.pos_id for item in calls[0]["positions"]} == {"1", "2"}

        assert calls[1]["captured_at"] == account_at
        assert calls[1]["snapshot"] is None
        assert {item.pos_id for item in calls[1]["positions"]} == {"1", "2"}
        assert {item.pos_id: item.size for item in calls[1]["positions"]}["1"] == Decimal("5")

        assert calls[2]["captured_at"] == account_at
        assert [item.pos_id for item in calls[2]["positions"]] == ["1"]

        closed = [
            event
            for event in events
            if event["type"] == "position.updated" and event["data"]["pos_id"] == "2"
        ]
        assert closed[-1]["data"]["size"] == "0"

    asyncio.run(scenario())


def test_account_update_with_only_one_currency_keeps_other_details() -> None:
    async def scenario() -> None:
        events: list[dict[str, Any]] = []
        hub = _hub(persist_snapshot=_no_persist)
        client = hub.register(events.append)
        client.account = True

        await hub._handle_account_row(_account_row(uTime="1794284760000"))
        await hub._handle_account_row(
            {
                "totalEq": "120",
                "availEq": "90",
                "imr": "30",
                "upl": "3",
                "uTime": "1794284770000",
                "details": [{"ccy": "BTC", "eq": "2", "cashBal": "2", "upl": "1"}],
            }
        )
        await hub.stop()

        accounts = [event for event in events if event["type"] == "account.snapshot.updated"]
        assert accounts[-1]["data"]["cash_balance"] == "50"
        assert accounts[-1]["data"]["equity"] == "120"
        assert accounts[-1]["data"]["unrealized_pnl"] == "3"

    asyncio.run(scenario())


def test_account_update_falls_back_to_merged_currency_detail() -> None:
    async def scenario() -> None:
        events: list[dict[str, Any]] = []
        hub = _hub(persist_snapshot=_no_persist)
        client = hub.register(events.append)
        client.account = True

        await hub._handle_account_row(_account_row(uTime="1794284760000"))
        await hub._handle_account_row(
            {
                "totalEq": "120",
                "imr": "30",
                "uTime": "1794284770000",
                "details": [{"ccy": "BTC", "eq": "2"}],
            }
        )
        await hub.stop()

        accounts = [event for event in events if event["type"] == "account.snapshot.updated"]
        assert accounts[-1]["data"]["available_equity"] == "80"
        assert accounts[-1]["data"]["used_margin"] == "30"

    asyncio.run(scenario())


def _fail_persist(**_kwargs: Any) -> None:
    raise RuntimeError("数据库不可用")


def _no_persist(**_kwargs: Any) -> None:
    return None


def test_publish_broadcasts_low_frequency_events() -> None:
    """`publish` 把提醒/活动等低频事件广播给所有已连接客户端。"""

    events: list[dict[str, Any]] = []

    async def scenario() -> None:
        hub = _hub()
        hub.register(events.append)
        await hub.publish(
            "alert.created",
            {"id": "al_1", "status": "pending"},
            as_of=datetime(2026, 11, 10, tzinfo=UTC),
        )
        await hub.stop()

    asyncio.run(scenario())
    assert [event["type"] for event in events] == ["alert.created"]
    assert events[0]["data"] == {"id": "al_1", "status": "pending"}


class RecordingPublic:
    """记录被订阅的标的，并在需要时暴露自己的实例给用例断言。"""

    instances: ClassVar[list[RecordingPublic]] = []

    def __init__(self, _on_status: Any) -> None:
        self.instruments: set[str] = set()
        self.stopped = False
        RecordingPublic.instances.append(self)

    def set_instruments(self, inst_ids: Any) -> None:
        self.instruments = set(inst_ids)

    async def messages(self):  # type: ignore[no-untyped-def]
        await asyncio.Event().wait()
        yield  # pragma: no cover


def test_resident_instruments_are_subscribed_without_any_browser() -> None:
    """AC1：没有浏览器连接时，关注列表里的标的仍然订阅着上游推送。"""

    async def scenario() -> None:
        RecordingPublic.instances.clear()
        hub = _hub(
            public_factory=RecordingPublic,
            watch_registry=WatchRegistry(tracked=lambda: ["XAAPL-USDT", "AAPL-USDT-SWAP"]),
        )
        hub.refresh_subscriptions()

        assert hub._public_task is not None
        assert RecordingPublic.instances[0].instruments == {"XAAPL-USDT", "AAPL-USDT-SWAP"}
        await hub.stop()

    asyncio.run(scenario())


def test_browser_subscriptions_are_added_on_top_of_the_resident_set() -> None:
    async def scenario() -> None:
        RecordingPublic.instances.clear()
        registry = WatchRegistry(tracked=lambda: ["XAAPL-USDT"])
        hub = _hub(public_factory=RecordingPublic, watch_registry=registry)
        registry.set_browser_source(hub.browser_instruments)
        hub.refresh_subscriptions()

        client = hub.register(lambda _event: None)
        await hub.subscribe(client, [{"type": "quote", "inst_ids": ["AAPL-USDT-SWAP"]}])

        assert RecordingPublic.instances[0].instruments == {"XAAPL-USDT", "AAPL-USDT-SWAP"}
        await hub.stop()

    asyncio.run(scenario())


def test_alerts_subscription_only_receives_alert_events() -> None:
    """浏览器 sink 的通道隔离：只看 `alerts` 位的连接才收告警。"""

    alerts: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []

    async def scenario() -> None:
        hub = _hub()
        watcher = hub.register(alerts.append)
        bystander = hub.register(others.append)
        await hub.subscribe(watcher, [{"type": "alerts"}])

        await hub.publish(
            "alert.created",
            {"id": "al_1"},
            as_of=datetime(2026, 11, 10, tzinfo=UTC),
            predicate=lambda client: bool(client.alerts),
        )
        await hub.stop()
        assert bystander.alerts is False

    asyncio.run(scenario())

    assert [event["type"] for event in alerts] == ["alert.created"]
    assert others == []


def test_market_push_is_emitted_to_the_pipeline_once(monkeypatch: Any) -> None:
    """hub 的行情 emit 点：一条推送交出一条事件，载荷是合并后的行情。"""

    emitted: list[Any] = []
    monkeypatch.setattr("app.stream.hub.emit", emitted.append)

    async def scenario() -> None:
        hub = _hub()
        hub._handle_market(
            MarketPush(
                "tickers",
                "XAAPL-USDT",
                {"instId": "XAAPL-USDT", "last": "231.42", "ts": "1794284760000"},
            )
        )
        hub._handle_market(
            MarketPush(
                "index-tickers",
                "XAAPL-USDT",
                {"instId": "XAAPL-USDT", "idxPx": "230.00", "ts": "1794284760000"},
            )
        )
        await hub.stop()

    asyncio.run(scenario())

    assert [event.kind for event in emitted] == ["quote", "quote"]
    assert emitted[0].inst_id == "XAAPL-USDT"
    assert emitted[1].payload["last"] == "231.42"
    assert emitted[1].payload["index"] == "230"


def test_private_updates_are_emitted_to_the_pipeline(monkeypatch: Any, client: Any) -> None:
    """私有 emit 点：账户与持仓状态更新各交出一条事件。"""

    sync_instruments([make_swap_ref()])
    emitted: list[Any] = []
    monkeypatch.setattr("app.stream.hub.emit", emitted.append)

    async def scenario() -> None:
        hub = _hub(persist_snapshot=_fail_persist)
        await hub._handle_account_row(_account_row(uTime="1794284760000"))
        await hub._handle_position_row(
            {
                "instId": "AAPL-USDT-SWAP",
                "posId": "pos-1",
                "posSide": "long",
                "pos": "2",
                "avgPx": "100",
                "markPx": "101",
                "upl": "2",
                "uplRatio": "0.01",
                "lever": "3",
                "mgnMode": "cross",
                "liqPx": "80",
                "margin": "10",
                "uTime": "1794284760000",
            }
        )
        await hub.stop()

    asyncio.run(scenario())

    assert [event.kind for event in emitted] == ["account", "position"]
    assert emitted[0].payload["equity"] == "100"
    assert emitted[1].inst_id == "AAPL-USDT-SWAP"


def test_only_closed_candles_reach_the_event_pipeline(monkeypatch: Any) -> None:
    """AC2：`confirm=0` 的推送不产生任何事件；`confirm=1` 只交出一根完整 K 线。"""

    emitted: list[Any] = []
    monkeypatch.setattr("app.stream.hub.emit", emitted.append)
    moment = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    candle = CandleShape(
        bar="1h",
        open_time=moment,
        open=Decimal("90"),
        high=Decimal("110"),
        low=Decimal("80"),
        close=Decimal("100"),
        volume=Decimal("12"),
        confirm=True,
    )
    hub = _hub()

    hub._handle_market(
        MarketPush(
            channel="candle1H",
            inst_id="XAAPL-USDT",
            row={"ts": "1794284760000", "confirm": "0"},
            candle=replace(candle, confirm=False),
        )
    )
    assert emitted == []

    hub._handle_market(
        MarketPush(
            channel="candle1H",
            inst_id="XAAPL-USDT",
            row={"ts": "1794284760000", "confirm": "1"},
            candle=candle,
        )
    )

    assert [event.kind for event in emitted] == ["candle.closed"]
    event = emitted[0]
    assert event.inst_id == "XAAPL-USDT"
    assert event.occurred_at == moment
    assert event.payload == {
        "bar": "1h",
        "open_time": "2026-11-20T12:00:00Z",
        "open": "90",
        "high": "110",
        "low": "80",
        "close": "100",
        "volume": "12",
        "confirm": True,
    }


def test_the_candle_connection_subscribes_the_same_instruments() -> None:
    """AC1：行情与 K 线两条连接订同一批标的，二者都只来自常驻集合。"""

    class Recording(IdlePublic):
        instances: ClassVar[list[Recording]] = []

        def __init__(self, on_status: Any) -> None:
            super().__init__(on_status)
            Recording.instances.append(self)

    async def scenario() -> None:
        Recording.instances.clear()
        hub = _hub(
            public_factory=Recording,
            candle_factory=Recording,
            watch_registry=WatchRegistry(tracked=lambda: ["XAAPL-USDT", "AAPL-USDT-SWAP"]),
        )
        hub.refresh_subscriptions()

        public, candles = Recording.instances
        assert public.instruments == {"XAAPL-USDT", "AAPL-USDT-SWAP"}
        assert candles.instruments == {"XAAPL-USDT", "AAPL-USDT-SWAP"}
        await hub.stop()

    asyncio.run(scenario())


def test_status_snapshot_reports_how_many_instruments_each_connection_subscribed() -> None:
    """AC5：健康接口读到的是连接真实的订阅数量与跳过数量，不是估出来的。"""

    hub = _hub()
    hub._public_client = SimpleNamespace(subscriptions=("XAAPL-USDT", "AAPL-USDT-SWAP"), skipped=1)
    hub._candle_client = SimpleNamespace(subscriptions=("XAAPL-USDT",), skipped=0)

    snapshot = hub.status_snapshot()

    assert (snapshot["subscriptions"], snapshot["skipped"]) == (2, 1)
    assert (snapshot["candle"]["subscriptions"], snapshot["candle"]["skipped"]) == (1, 0)


def test_status_snapshot_reports_the_private_connection_state() -> None:
    """私有推送是否真的连上必须读得到：它按需启动，不能用公共连接的状态代替。"""

    hub = _hub()
    hub._set_status(PRIVATE_DATASET, True, "")

    snapshot = hub.status_snapshot()

    assert snapshot["private"]["dataset"] == "private_ws"
    assert snapshot["private"]["connected"] is True
    assert snapshot["private"]["ever_connected"] is True
    assert snapshot["private"]["last_error"] is None


def test_status_snapshot_keeps_a_private_login_failure_visible() -> None:
    """启动后登录失败：`connected` 与 `last_success_at` 都为空，只能靠 `last_error` 分辨。"""

    hub = _hub()
    hub._set_status(PRIVATE_DATASET, False, "WebSocket 连续断开 5 次后放弃重连:4001 Login failed.")

    snapshot = hub.status_snapshot()

    assert snapshot["private"]["connected"] is False
    assert snapshot["private"]["ever_connected"] is False
    assert snapshot["private"]["last_success_at"] is None
    assert "4001" in snapshot["private"]["last_error"]


def test_a_candle_reconnect_does_not_trigger_a_private_reconcile(client: Any) -> None:
    """K 线重连只恢复订阅：账户对账属于私有连接，不能被这一路重连带起来。"""

    calls: list[str] = []
    hub = _hub(account_sync=lambda: calls.append("account"))

    hub._set_status(CANDLE_DATASET, True, "")
    hub._set_status(CANDLE_DATASET, False, "断开")
    hub._set_status(CANDLE_DATASET, True, "")

    assert hub._reconcile_tasks == set()
    assert calls == []

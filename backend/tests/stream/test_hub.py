"""浏览器推送：订阅过滤、节流、去重、私有推送与写库失败降级。

上游用空闲的假客户端替代，测试直接调用推送入口驱动事件，不连 OKX、不写数据库。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.exchange import MarketPush
from app.instrument import sync_instruments
from app.positions import ExchangePositionView
from app.stream import StreamHub
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
        "credentials_configured": lambda: False,
    }
    options.update(overrides)
    return StreamHub(**options)


def _quotes(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event["type"] == "market.quote.updated"]


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
            ]
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

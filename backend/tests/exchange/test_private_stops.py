"""止损委托与订单历史的适配层映射。

两件事必须区分开：**查询成功且没有任何止损**返回空列表，**查询失败**要抛异常。
把它们合成一个「空结果」，界面上「没设止损」与「没查到」就再也分不开了。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core import OrderRecord, StopOrder
from app.exchange import ExchangeError, OkxPrivateClient
from tests.exchange.conftest import FROZEN_NOW, SWAP_INST_ID
from tests.fakes.okx.server import FakeOkxServer

#: 冻结时钟的毫秒时间戳：订单的 `cTime` 必须落在 `order_history` 的回溯窗口里，
#: 否则会被「最多 3 个月」的过滤条件正确剔除，用例就测不到翻页。
_NOW_MS = int(FROZEN_NOW.timestamp() * 1000)


def _minutes_ago(minutes: int) -> int:
    return _NOW_MS - minutes * 60_000


def test_stop_orders_read_every_algo_type(
    trade: OkxPrivateClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    book = fake_okx_server.store.book
    book.set_stop(SWAP_INST_ID, stop_px="90", algo_type="conditional")
    book.set_stop(SWAP_INST_ID, stop_px="85", algo_type="oco")
    book.set_stop(SWAP_INST_ID, stop_px="80", algo_type="move_order_stop")
    book.set_stop(SWAP_INST_ID, stop_px="75", algo_type="trigger")

    stops = trade.stop_orders()

    assert sorted(stop.stop_px for stop in stops if stop.stop_px is not None) == [
        Decimal("75"),
        Decimal("80"),
        Decimal("85"),
        Decimal("90"),
    ]
    queried = {
        query.split("ordType=")[1].split("&")[0]
        for method, path, query, _body in book.requests
        if method == "GET" and path == "/api/v5/trade/orders-algo-pending"
    }
    assert queried == {"conditional", "oco", "move_order_stop", "trigger"}


def test_take_profit_only_orders_have_no_stop_price(
    trade: OkxPrivateClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    """只带止盈的委托：有行、但 `stop_px` 为空，不能算「已挂止损」。"""

    fake_okx_server.store.book.set_stop(SWAP_INST_ID, take_profit_px="120")

    stops = trade.stop_orders()

    assert len(stops) == 1
    assert stops[0].stop_px is None


def test_stop_orders_come_back_empty_when_nothing_is_placed(
    trade: OkxPrivateClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    assert trade.stop_orders() == []


def test_stop_orders_raise_when_upstream_fails(
    trade: OkxPrivateClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    fake_okx_server.scenarios.activate("upstream_error")

    with pytest.raises(ExchangeError):
        trade.stop_orders()


def test_order_history_merges_open_and_closed_newest_first(
    trade: OkxPrivateClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    book = fake_okx_server.store.book
    book.add_historical_order(
        SWAP_INST_ID,
        side="buy",
        qty="2",
        avg_px="100",
        pnl="1.5",
        fee="-0.03",
        created_at=_minutes_ago(30),
    )
    book.add_historical_order(
        SWAP_INST_ID,
        side="sell",
        qty="1",
        avg_px="110",
        pnl="2.5",
        fee="-0.02",
        created_at=_minutes_ago(10),
    )
    book.add_historical_order(
        SWAP_INST_ID,
        state="live",
        qty="3",
        price="120",
        created_at=_minutes_ago(20),
    )

    records = trade.order_history(SWAP_INST_ID)

    assert [record.ts.timestamp() for record in records] == sorted(
        (record.ts.timestamp() for record in records), reverse=True
    )
    assert [record.is_open for record in records] == [False, True, False]
    assert all(isinstance(record, OrderRecord) for record in records)
    assert records[1].qty == Decimal("3")


def test_order_history_keeps_the_upstream_fields(
    trade: OkxPrivateClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    fake_okx_server.store.book.add_historical_order(
        SWAP_INST_ID,
        side="sell",
        qty="0.2",
        price="60520",
        avg_px="60520",
        pnl="1.84",
        fee="-0.03",
        created_at=_minutes_ago(30),
    )

    record = trade.order_history(SWAP_INST_ID)[0]

    assert record.side == "sell"
    assert record.price == Decimal("60520")
    assert record.avg_px == Decimal("60520")
    assert record.pnl == Decimal("1.84")
    assert record.fee == Decimal("-0.03")
    assert record.status == "filled"
    assert isinstance(record, OrderRecord)


def test_stop_orders_are_stop_order_values(
    trade: OkxPrivateClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    fake_okx_server.store.book.set_stop(SWAP_INST_ID, stop_px="90", pos_side="long")

    stop = trade.stop_orders()[0]

    assert isinstance(stop, StopOrder)
    assert stop.inst_id == SWAP_INST_ID
    assert stop.pos_side == "long"


def test_order_history_pages_with_after_ord_id(
    trade: OkxPrivateClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    """超过单页 100 条时要向更早翻页，游标是 `ordId` 而不是时间戳。

    OKX 的分页语义容易记反：`after` 取更早、`before` 取更新，两者的值都是 `ordId`。
    写反方向或传时间戳时，第二页要么被上游拒（弹窗整体 502），要么反复返回同一页
    （更早的订单永远取不到）。假服务端现在按同一套语义切片，这段行为才被真正覆盖。
    """

    book = fake_okx_server.store.book
    for index in range(130):
        book.add_historical_order(
            SWAP_INST_ID,
            side="buy",
            qty="1",
            avg_px="100",
            created_at=_minutes_ago(130 - index),
        )

    records = trade.order_history(SWAP_INST_ID)

    assert len(records) == 130
    assert len({record.order_id for record in records}) == 130
    history_queries = [
        query
        for method, path, query, _body in book.requests
        if method == "GET"
        and path in {"/api/v5/trade/orders-history", "/api/v5/trade/orders-history-archive"}
    ]
    assert any("after=" in query for query in history_queries), history_queries
    assert all("before=" not in query for query in history_queries), history_queries
    # 游标必须是 ordId，不是 cTime 毫秒
    cursors = [
        query.split("after=")[1].split("&")[0] for query in history_queries if "after=" in query
    ]
    assert all(not cursor.isdigit() for cursor in cursors), cursors


def test_finished_orders_do_not_count_as_a_live_stop(
    trade: OkxPrivateClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    """已成交订单上的 `slTriggerPx` 是历史记录，不是活着的止损。"""

    fake_okx_server.store.book.add_historical_order(
        SWAP_INST_ID,
        side="sell",
        qty="1",
        stop_px="90",
        state="filled",
        created_at=_minutes_ago(30),
    )

    assert trade.stop_orders() == []

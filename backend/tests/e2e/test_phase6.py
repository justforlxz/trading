"""Phase 6 端到端：下单 → 部分成交 → 断线 → 重连 → 对账。

链路用假 OKX 的真实私有接口（签名、下单、查单、成交、持仓）跑一遍：

1. 新进程向假交易所提交一张限价单，交易所侧只有这一张单。
2. 交易所分两笔部分成交（2 + 1），订单状态变成 `partially_filled`。
3. 断线后用一个新的客户端重连，本地状态为空：从交易所快照恢复出订单与两笔成交。
4. 把恢复出的新成交记进策略虚拟账本，实际持仓与虚拟持仓一致，差额清单为空。
5. 用同一个 `clientOrderId` 重发：不会产生第二张单。
6. 对账前后虚拟账本逐字段相同：对账只读，不抹平。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.config import Settings
from app.core import OrderIntent, ReplayClock
from app.exchange import create_trade_port
from app.execution import (
    NET_POS_SIDE,
    STATUS_PARTIALLY_FILLED,
    ExecutionState,
    ReconcileHolding,
    VenueSnapshot,
    fetch_actual_positions,
    from_venue_order,
    reconcile_positions,
    recover_state,
)
from app.instrument import list_instruments, sync_instruments
from app.portfolio import get_portfolio, record_fill
from tests.factories.instruments import make_swap_ref
from tests.fakes.okx.server import FakeOkxServer

D = Decimal
SWAP_INST_ID = "AAPL-USDT-SWAP"
AS_OF = datetime(2026, 11, 12, 3, 30, 0, tzinfo=UTC)
CLIENT_ORDER_ID = "p6recover1"


def _settings(server: FakeOkxServer) -> Settings:
    credentials = server.store.book.credentials
    return Settings(
        okx_rest_base_url=server.base_url,
        okx_http_timeout_seconds=10.0,
        okx_http_max_retries=0,
        okx_rate_limit_capacity=1000,
        okx_rate_limit_refill_per_second=1000.0,
        okx_api_key=credentials.api_key,
        okx_secret_key=credentials.secret,
        okx_passphrase=credentials.passphrase,
        okx_demo=True,
    )


def _intent() -> OrderIntent:
    return OrderIntent(
        inst_id=SWAP_INST_ID,
        side="buy",
        qty=D("5"),
        order_type="limit",
        price=D("100"),
        client_order_id=CLIENT_ORDER_ID,
        pos_side=NET_POS_SIDE,
    )


def _virtual_holdings(instance_id: str) -> tuple[ReconcileHolding, ...]:
    detail = get_portfolio(instance_id)
    assert detail is not None
    return tuple(
        ReconcileHolding(
            product_key=position.product_key,
            inst_type=position.inst_type,
            side=position.direction,
            qty=position.qty,
            avg_cost=position.avg_cost,
        )
        for position in detail.positions
    )


def test_order_partial_fill_disconnect_reconnect_and_reconcile(
    client: TestClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    sync_instruments([make_swap_ref()])
    created = client.post(
        "/api/strategy-instances",
        json={
            "strategy_id": "relative_value",
            "name": "AAPL 永续对账",
            "bar": "1d",
            "inst_ids": [SWAP_INST_ID],
        },
    )
    assert created.status_code == 201, created.text
    instance_id = str(created.json()["instance_id"])

    book = fake_okx_server.store.book
    settings = _settings(fake_okx_server)
    clock = ReplayClock(AS_OF)

    # 1. 下单：交易所侧一张挂单。
    trade = create_trade_port(settings=settings, clock=clock)
    try:
        venue_order = trade.place(_intent())
    finally:
        trade.close()
    assert book.order_count == 1

    # 2. 两笔部分成交：2 + 1，订单仍挂 3 未成交。
    book.fill_order(venue_order.order_id, qty="2", price="100")
    book.fill_order(venue_order.order_id, qty="1", price="100")
    book.set_position(SWAP_INST_ID, qty="3", pos_side="long", avg_price="100")

    # 3. 断线重连：新客户端、空本地状态，从交易所快照恢复。
    # 假交易所的订单时间来自真实时钟；恢复时间不能早于它。
    recovery_now = datetime.now(UTC)
    trade = create_trade_port(settings=settings, clock=clock)
    try:
        venue_order = trade.order(SWAP_INST_ID, venue_order.order_id)
        fills = tuple(trade.fills(SWAP_INST_ID, venue_order.order_id))
        actual = fetch_actual_positions(trade, list_instruments())
        recovered = recover_state(
            ExecutionState(),
            VenueSnapshot(
                orders=(from_venue_order(venue_order, pos_side=NET_POS_SIDE),),
                fills=fills,
                positions=actual,
            ),
            now=recovery_now,
        )

        assert len(recovered.state.orders) == 1
        (order,) = recovered.state.orders
        assert order.status == STATUS_PARTIALLY_FILLED
        assert order.filled_qty == D("3")
        assert recovered.unfinished_orders == (order,)
        assert len(recovered.new_fills) == 2

        # 4. 新成交记进策略虚拟账本，两侧收敛。
        for fill in recovered.new_fills:
            record_fill(
                instance_id,
                inst_id=fill.inst_id,
                side=fill.side,
                qty=fill.qty,
                price=fill.price,
                at=fill.ts,
            )

        virtual_before = _virtual_holdings(instance_id)
        report = reconcile_positions(
            actual,
            virtual_before,
            as_of=recovery_now,
            orders=recovered.state.orders,
            instruments=list_instruments(),
        )
        assert report.differences == ()
        assert report.balanced is True

        # 6. 对账前后虚拟账本逐字段相同：只读，不抹平。
        assert _virtual_holdings(instance_id) == virtual_before
        assert actual == fetch_actual_positions(trade, list_instruments())

        # 5. 同一个 clientOrderId 重发：仍是同一张单，不产生第二张。
        replayed = trade.place(_intent())
        assert replayed.order_id == order.order_id
        assert book.order_count == 1
    finally:
        trade.close()

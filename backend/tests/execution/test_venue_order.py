"""交易所订单归一：真实下单入口与 paper 入口产出同一种订单对象。

判据来源（MKACG-730 功能检测 AC-4）：`OkxPrivateClient.place()` 返回 `core.Order`，
其中 `status` 是上游字面量（`live` / `canceled`）。执行域必须先归一，才能和 paper
侧一样参与状态机与下游比较；这条用例走真实适配器与假 OKX，不手工重建交易所订单。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.config import Settings
from app.core import Order as VenueOrder
from app.core import ReplayClock, ValidationError
from app.db import init_db
from app.exchange import OkxPrivateClient, create_trade_port
from app.exchange.okx.instruments import parse_instruments
from app.execution import (
    STATUS_CANCELLED,
    STATUS_FILLED,
    STATUS_OPEN,
    STATUS_PARTIALLY_FILLED,
    Order,
    PaperBroker,
    from_venue_order,
)
from app.instrument import Instrument, sync_instruments
from tests.execution.conftest import SPOT_INST_ID, SWAP_INST_ID, make_intent
from tests.fakes.okx.server import FakeOkxServer

SPOT = "SPOT"
SWAP = "SWAP"
FROZEN_NOW = datetime(2026, 11, 12, 3, 0, 0, tzinfo=UTC)
ZERO = Decimal(0)

#: 与 `tests/exchange/conftest.py` 同形：上游 `/public/instruments` 的现货行。
SPOT_INSTRUMENT = {
    "instId": SPOT_INST_ID,
    "instType": SPOT,
    "baseCcy": "XAAPL",
    "quoteCcy": "USDT",
    "state": "live",
    "instCategory": "3",
    "tickSz": "0.01",
    "lotSz": "0.001",
    "minSz": "0.01",
    "listTime": "1760000000000",
}

#: 与 `tests/exchange/conftest.py` 同形：上游 `/public/instruments` 的永续行。
SWAP_INSTRUMENT = {
    "instId": SWAP_INST_ID,
    "instType": SWAP,
    "baseCcy": "",
    "quoteCcy": "",
    "ctValCcy": "AAPL",
    "settleCcy": "USDT",
    "ctVal": "1",
    "ctMult": "1",
    "ctType": "linear",
    "lever": "20",
    "state": "live",
    "instCategory": "3",
    "tickSz": "0.01",
    "lotSz": "0.1",
    "minSz": "0.1",
    "listTime": "1760000000000",
}


@pytest.fixture()
def venue_trade(fake_okx_server: FakeOkxServer) -> Iterator[OkxPrivateClient]:
    """真实适配器指向假 OKX；标的表与幂等登记表按生产路径建好。"""

    init_db()
    sync_instruments(parse_instruments([SPOT_INSTRUMENT, SWAP_INSTRUMENT]))
    credentials = fake_okx_server.store.book.credentials
    settings = Settings(
        okx_rest_base_url=fake_okx_server.base_url,
        okx_http_max_retries=0,
        okx_rate_limit_capacity=1000,
        okx_rate_limit_refill_per_second=1000.0,
        okx_api_key=credentials.api_key,
        okx_secret_key=credentials.secret,
        okx_passphrase=credentials.passphrase,
        okx_demo=True,
    )
    client = create_trade_port(settings=settings, clock=ReplayClock(FROZEN_NOW))
    yield client
    client.close()


def _venue_order(*, status: str, filled_qty: str = "0", qty: str = "2") -> VenueOrder:
    return VenueOrder(
        order_id="ord-from-venue",
        client_order_id="venue1",
        inst_id=SPOT_INST_ID,
        side="buy",
        order_type="limit",
        qty=Decimal(qty),
        price=Decimal("100"),
        filled_qty=Decimal(filled_qty),
        status=status,
        ts=FROZEN_NOW,
    )


@pytest.mark.parametrize(
    ("venue_status", "expected"),
    [
        ("live", STATUS_OPEN),
        ("partially_filled", STATUS_PARTIALLY_FILLED),
        ("filled", STATUS_FILLED),
        ("canceled", STATUS_CANCELLED),
        ("mmp_canceled", STATUS_CANCELLED),
    ],
)
def test_venue_statuses_are_mapped_to_the_execution_vocabulary(
    venue_status: str, expected: str
) -> None:
    filled_qty = {"partially_filled": "1", "filled": "2"}.get(venue_status, "0")

    order = from_venue_order(_venue_order(status=venue_status, filled_qty=filled_qty))

    assert type(order) is Order
    assert order.status == expected
    assert order.filled_qty == Decimal(filled_qty)
    assert order.order_id == "ord-from-venue"
    assert order.created_at == FROZEN_NOW
    assert order.updated_at == FROZEN_NOW


def test_unknown_venue_status_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        from_venue_order(_venue_order(status="rejected"))


def test_a_normalized_venue_order_reports_unknown_cost_instead_of_zero() -> None:
    """`core.Order` 不带成交金额：均价是未知，不是 0。"""

    order = from_venue_order(_venue_order(status="filled", filled_qty="2"))

    assert order.filled_cost == ZERO
    assert order.avg_fill_price is None


def test_venue_entry_and_paper_entry_produce_the_same_order_object(
    venue_trade: OkxPrivateClient,
    fake_okx_server: FakeOkxServer,
    spot_instrument: Instrument,
) -> None:
    """真正经过 `OkxPrivateClient.place()`：两条入口都得到执行域 `Order`。"""

    fake_okx_server.store.book.set_balance("USDT", available="10000")
    fake_okx_server.store.book.set_mark_price(SPOT_INST_ID, "100")
    intent = make_intent(client_order_id="venuepaper", qty="2")

    venue_order = from_venue_order(venue_trade.place(intent))
    paper_order = PaperBroker(fee_rate=Decimal("0.0005"), slippage=Decimal("0.001")).place(
        intent,
        spot_instrument,
        market_price=Decimal("100"),
        now=FROZEN_NOW,
    )

    assert type(paper_order) is Order
    assert type(venue_order) is type(paper_order)
    assert venue_order.status == paper_order.status == STATUS_FILLED
    assert venue_order.filled_qty == paper_order.filled_qty == Decimal("2")
    assert venue_order.client_order_id == paper_order.client_order_id == "venuepaper"


def test_normalized_swap_order_keeps_the_hedge_leg_and_reduce_only(
    venue_trade: OkxPrivateClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    """真正经过真实适配器的永续单：归一后持仓腿与只减仓语义不能丢。"""

    fake_okx_server.store.book.set_balance("USDT", available="10000")
    intent = make_intent(
        client_order_id="swaphedge",
        inst_id=SWAP_INST_ID,
        order_type="limit",
        price="100",
        pos_side="short",
        reduce_only=True,
    )

    venue_order = venue_trade.place(intent)
    order = from_venue_order(venue_order, pos_side=intent.pos_side, reduce_only=intent.reduce_only)

    assert order.inst_id == SWAP_INST_ID
    assert order.pos_side == "short"
    assert order.reduce_only is True
    assert order.status == STATUS_OPEN


def test_normalized_order_without_the_intent_defaults_to_net_and_open() -> None:
    """没传意图时按单向模式、非只减仓处理：不编造一个方向。"""

    order = from_venue_order(_venue_order(status="live"))

    assert order.pos_side == ""
    assert order.reduce_only is False

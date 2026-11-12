"""执行域用例的公共装配：两条标的、固定时钟，以及手算用例要用的构造函数。

持仓归一与撮合只**读**标的行的字段（产品键、类别、报价币种、结算币种），不需要落库：
这里直接构造标的行对象。落库路径（`sync_instruments`）已由标的与交易所域的用例覆盖，
本域不再为「读一条持仓」付出一次迁移。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core import Fill, Money, OrderIntent
from app.instrument import Instrument

SPOT = "SPOT"
SWAP = "SWAP"
SPOT_INST_ID = "XAAPL-USDT"
SWAP_INST_ID = "AAPL-USDT-SWAP"
PRODUCT_KEY = "AAPL"
QUOTE_CURRENCY = "USDT"
FROZEN_NOW = datetime(2026, 11, 12, 3, 0, 0, tzinfo=UTC)


def _instrument(**overrides: object) -> Instrument:
    row = {
        "symbol": SPOT_INST_ID,
        "inst_type": SPOT,
        "product_key": PRODUCT_KEY,
        "asset_type": "tokenized_equity",
        "exchange": "okx",
        "base_currency": PRODUCT_KEY,
        "quote_currency": QUOTE_CURRENCY,
        "tick_size": Decimal("0.01"),
        "lot_size": Decimal("0.001"),
        "min_order_size": Decimal("0.001"),
        "trading_status": "live",
    }
    row.update(overrides)
    return Instrument(**row)


@pytest.fixture()
def spot_instrument() -> Instrument:
    """代币化股票的现货形态。"""

    return _instrument()


@pytest.fixture()
def swap_instrument() -> Instrument:
    """同一产品的永续形态：结算币种为 USDT，精度与类别字段与现货不同。"""

    return _instrument(
        symbol=SWAP_INST_ID,
        inst_type=SWAP,
        settle_ccy=QUOTE_CURRENCY,
        ct_val=Decimal("1"),
        ct_mult=Decimal("1"),
        max_lever=Decimal("20"),
    )


def make_intent(
    *,
    client_order_id: str = "cli1",
    inst_id: str = SPOT_INST_ID,
    side: str = "buy",
    order_type: str = "market",
    qty: str = "2",
    price: str | None = None,
    pos_side: str = "",
    reduce_only: bool = False,
) -> OrderIntent:
    """构造一笔下单意图；数值用字符串写，避免二进制浮点混进来。"""

    return OrderIntent(
        inst_id=inst_id,
        side=side,
        qty=Decimal(qty),
        order_type=order_type,
        price=None if price is None else Decimal(price),
        client_order_id=client_order_id,
        pos_side=pos_side,
        reduce_only=reduce_only,
    )


def make_fill(
    *,
    order_id: str = "",
    inst_id: str = SPOT_INST_ID,
    side: str = "buy",
    qty: str = "2",
    price: str = "100",
    fee: str = "0",
    fee_currency: str = QUOTE_CURRENCY,
    fill_id: str = "fill1",
    ts: datetime = FROZEN_NOW,
) -> Fill:
    """构造一笔成交记录。"""

    return Fill(
        fill_id=fill_id,
        order_id=order_id,
        inst_id=inst_id,
        side=side,
        qty=Decimal(qty),
        price=Decimal(price),
        fee=Money(Decimal(fee), fee_currency),
        ts=ts,
    )

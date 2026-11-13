"""对账取数：假 OKX 的两类实际持仓都能读出来并对上。

判据来源（MKACG-736）：

- SWAP 读持仓接口；SPOT 由余额明细推导（可用量 + 冻结量），两条路径产出同一种形状。
- SPOT 侧出现差额时，清单里的实际数量与交易所余额明细的可用量 + 冻结量对得上。
"""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from app.config import Settings
from app.core import ReplayClock
from app.exchange import create_trade_port
from app.execution import (
    NET_POS_SIDE,
    SIDE_LONG,
    ReconcileHolding,
    fetch_actual_positions,
    reconcile_positions,
)
from app.instrument import list_instruments, sync_instruments
from tests.execution.conftest import FROZEN_NOW, PRODUCT_KEY
from tests.factories.instruments import make_ref, make_swap_ref
from tests.fakes.okx.server import FakeOkxServer

D = Decimal
SPOT_INST_ID = "XAAPL-USDT"
SWAP_INST_ID = "AAPL-USDT-SWAP"


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


def test_both_position_sources_produce_comparable_actual_positions(
    client: TestClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    """SPOT 2.5 + 冻结 0.5 = 3；SWAP 读持仓接口 2；两者都能参与同一套比较。"""

    sync_instruments([make_ref(), make_swap_ref()])
    book = fake_okx_server.store.book
    book.set_balance("XAAPL", available="2.5", frozen="0.5", avg_price="350")
    book.set_position(SWAP_INST_ID, qty="2", pos_side="long", avg_price="99.5")

    trade = create_trade_port(settings=_settings(fake_okx_server), clock=ReplayClock(FROZEN_NOW))
    try:
        actual = fetch_actual_positions(trade, list_instruments())
    finally:
        trade.close()

    held = {position.inst_type: position for position in actual}
    assert held["SPOT"].product_key == PRODUCT_KEY
    assert held["SPOT"].qty == D("3")
    assert held["SPOT"].avg_cost == D("350")
    assert held["SWAP"].qty == D("2")
    assert held["SWAP"].avg_cost == D("99.5")
    assert held["SWAP"].pos_side == NET_POS_SIDE

    detail = book.balance("XAAPL")["details"][0]
    assert held["SPOT"].qty == D(detail["availBal"]) + D(detail["frozenBal"])


def test_spot_quantity_difference_is_explained_by_available_plus_frozen(
    client: TestClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    """虚拟侧 2、交易所侧 2.5 + 0.5 = 3：差额 1、百分比 50%。"""

    sync_instruments([make_ref()])
    book = fake_okx_server.store.book
    book.set_balance("XAAPL", available="2.5", frozen="0.5", avg_price="350")

    trade = create_trade_port(settings=_settings(fake_okx_server), clock=ReplayClock(FROZEN_NOW))
    try:
        actual = fetch_actual_positions(trade, list_instruments())
    finally:
        trade.close()

    report = reconcile_positions(
        actual,
        (
            ReconcileHolding(
                product_key=PRODUCT_KEY,
                inst_type="SPOT",
                side=SIDE_LONG,
                qty=D("2"),
                avg_cost=D("350"),
            ),
        ),
        as_of=FROZEN_NOW,
    )

    (item,) = report.differences
    assert item.product_key == PRODUCT_KEY
    assert item.actual_qty == D("3")
    assert item.qty_diff == D("1")
    assert item.qty_diff_pct == D("50")
    assert item.cause == "manual_intervention"

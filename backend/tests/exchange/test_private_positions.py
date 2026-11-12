"""持仓与余额：两类来源不同、形状相同。

MKACG-729 的两条判据：

- 永续读持仓接口；现货的 `/account/positions?instType=SPOT` 上游返回 `51000`，
  必须由余额明细推导，而且**两条路径产出的字段集合相同**。
- 现货口径显式定义：持仓量 = 可用量 + 冻结量，成本价取上游 `avgPx`（没有就记 0，
  表示成本未知）。
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from app.core import DataUnavailable, Money, Position
from app.exchange import OkxPrivateClient, create_trade_port
from app.exchange.okx.instruments import parse_instruments
from app.instrument import sync_instruments
from tests.exchange.conftest import SPOT_INST_ID, SPOT_INSTRUMENT, SWAP_INST_ID
from tests.factories.instruments import load_all_instruments
from tests.fakes.okx.server import FakeOkxServer


def test_swap_positions_are_read_from_the_positions_endpoint(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """永续：多头为正、空头为负，成本与未实现盈亏原样映射。"""

    book = fake_okx_server.store.book
    book.set_position(SWAP_INST_ID, qty="3", pos_side="long", avg_price="99.5", upl="12.75")
    book.set_position(SWAP_INST_ID, qty="2", pos_side="short", avg_price="101", upl="-4")

    legs = [position for position in trade.positions() if position.inst_id == SWAP_INST_ID]

    assert [leg.qty for leg in legs] == [Decimal("3"), Decimal("-2")]
    assert legs[0].avg_price == Decimal("99.5")
    assert legs[0].unrealized_pnl == Money(Decimal("12.75"), "USDT")
    assert any(
        method == "GET" and path == "/api/v5/account/positions"
        for method, path, _query, _body in book.requests
    )


def test_spot_positions_are_derived_from_balance_details(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """现货：持仓量 = 可用量 + 冻结量，成本取 `avgPx`，盈亏取 `upl`。"""

    book = fake_okx_server.store.book
    book.set_balance("XAAPL", available="2.5", frozen="0.5", avg_price="350", upl="7")

    held = {position.inst_id: position for position in trade.positions()}

    assert held[SPOT_INST_ID].qty == Decimal("3.0")
    assert held[SPOT_INST_ID].avg_price == Decimal("350")
    assert held[SPOT_INST_ID].unrealized_pnl == Money(Decimal("7"), "USDT")


def test_spot_positions_map_to_the_traded_quote_when_many_quotes_exist(
    private_settings, frozen_clock, trade_schema, fake_okx_server: FakeOkxServer
) -> None:
    """全类别标的表 + 只持 BTC 与 USDT：只推导出 `BTC-USDT`，现金不成为持仓。

    OKX 上同一币种还挂着 `BTC-AED`、`ETH-BTC` 这类报价。按符号排序取「最靠前的一档」
    会把 BTC 记到 AED 报价的标的上，还会把 USDT 现金记成一条 `USDT-AED` 多头——
    两条都是账户里不存在的持仓，对账因此永远对不平。
    """

    sync_instruments(parse_instruments(load_all_instruments()))
    book = fake_okx_server.store.book
    book.set_balance("BTC", available="1.0015")
    book.set_balance("USDT", available="3090.9", frozen="100")

    client = create_trade_port(settings=private_settings, clock=frozen_clock)
    try:
        held = client.positions()
    finally:
        client.close()

    assert [position.inst_id for position in held] == ["BTC-USDT"]
    assert held[0].qty == Decimal("1.0015")
    assert held[0].unrealized_pnl.currency == "USDT"


def test_spot_position_cost_is_unknown_rather_than_fabricated(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """上游对纯现货现金余额不下发 `avgPx`：成本记 0（未知），不拿现价冒充。"""

    fake_okx_server.store.book.set_balance("XAAPL", available="1")

    held = {position.inst_id: position for position in trade.positions()}

    assert held[SPOT_INST_ID].qty == Decimal("1")
    assert held[SPOT_INST_ID].avg_price == Decimal("0")


def test_spot_positions_never_ask_the_positions_endpoint(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """现货那条路径一次都不该请求持仓接口：上游对它只会回 51000。"""

    fake_okx_server.store.book.set_balance("XAAPL", available="1")

    trade.positions()

    asked = [
        (method, path, query)
        for method, path, query, _body in fake_okx_server.store.book.requests
        if path == "/api/v5/account/positions"
    ]
    assert all("SPOT" not in query for _method, _path, query in asked)


def test_both_position_sources_produce_the_same_field_set(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """两条路径都产出 `core.Position`：字段集合与类型逐一相同。"""

    book = fake_okx_server.store.book
    book.set_position(SWAP_INST_ID, qty="1", pos_side="long", avg_price="100", upl="1")
    book.set_balance("XAAPL", available="1", avg_price="350")

    held = {position.inst_id: position for position in trade.positions()}
    swap_leg = held[SWAP_INST_ID]
    spot_leg = held[SPOT_INST_ID]

    # 判据是「两条路径都把同一份形状填满」：先钉住端口声明的字段集合，再逐个字段
    # 断言实例上的真实取值类型。只比较两个实例的 `__slots__` 等于拿同一个 dataclass
    # 跟自己比，恒为真，什么也没验证。
    declared = {
        "inst_id": str,
        "qty": Decimal,
        "avg_price": Decimal,
        "unrealized_pnl": Money,
    }
    assert {field.name for field in dataclasses.fields(Position)} == set(declared)
    for leg in (swap_leg, spot_leg):
        assert isinstance(leg, Position)
        for name, kind in declared.items():
            assert isinstance(getattr(leg, name), kind)


def test_zero_holdings_do_not_appear(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """无持仓的标的不出现：余额里挂着一堆零数量币种也不该变成持仓。"""

    book = fake_okx_server.store.book
    book.set_balance("XAAPL", available="0", frozen="0")
    book.set_position(SWAP_INST_ID, qty="0", pos_side="net", avg_price="0")

    assert trade.positions() == []


def test_the_category_set_comes_from_the_rules_not_the_instrument_table(
    private_settings, frozen_clock, trade_schema, fake_okx_server: FakeOkxServer
) -> None:
    """只同步到现货标的时，永续持仓照样要去查：类别取自规则表，不是库里有哪些行。"""

    sync_instruments(parse_instruments([SPOT_INSTRUMENT]))
    fake_okx_server.store.book.set_position(SWAP_INST_ID, qty="2", pos_side="long", avg_price="100")
    client = create_trade_port(settings=private_settings, clock=frozen_clock)
    try:
        held = client.positions()
    finally:
        client.close()

    assert [position.inst_id for position in held] == [SWAP_INST_ID]


def test_an_empty_instrument_table_is_reported_not_treated_as_no_positions(
    private_settings, frozen_clock, trade_schema
) -> None:
    """标的表为空说明还没同步标的：明确报错，不能静默返回一份空持仓。"""

    client = create_trade_port(settings=private_settings, clock=frozen_clock)
    try:
        with pytest.raises(DataUnavailable):
            client.positions()
    finally:
        client.close()


def test_currencies_without_a_spot_instrument_are_not_positions(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """余额里没有对应现货标的的币种（例如 USDT 现金本身）不算持仓。"""

    fake_okx_server.store.book.set_balance("USDT", available="1000")

    assert trade.positions() == []


def test_balance_returns_the_available_amount(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    fake_okx_server.store.book.set_balance("USDT", available="123.45", frozen="10")

    assert trade.balance("USDT") == Money(Decimal("123.45"), "USDT")


def test_a_currency_the_account_does_not_hold_is_zero(
    trade: OkxPrivateClient,
) -> None:
    """没有这个币种记 0 而不是报错：余额查询要能回答「能不能买」。"""

    assert trade.balance("USDT") == Money(Decimal("0"), "USDT")

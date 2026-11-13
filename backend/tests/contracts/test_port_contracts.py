"""core 冻结层的契约测试。

这里固定的是「所有实现方都要遵守」的那部分语义，分成三块：

- 值对象与错误的不可变、封闭性——改动它们会静默污染全仓，所以逐条钉住。
- 端口契约 mixin——`tests/fakes/okx` 与真实 OKX 适配器继承同一组断言，避免「两个
  实现两种语义」。美股代理源（`us_equity_proxy`）刻意不下发标的元数据、不提供实时
  快照，因此有自己的一组断言（`tests/exchange/test_us_equity.py`）。
- registry / clock 这两个跨模块原语的行为。

构造数据一律来自 `conftest.py` 的 fixture。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core import (
    Bar,
    Clock,
    Conflict,
    DataUnavailable,
    ExecutionRejected,
    Fill,
    InstrumentRef,
    InvariantViolation,
    MarketDataPort,
    Money,
    Order,
    OrderIntent,
    Position,
    ReplayClock,
    RiskBlocked,
    Signal,
    SystemClock,
    Ticker,
    Timeframe,
    TradePort,
    TradingError,
    UnprocessableEntity,
    UpstreamError,
    ValidationError,
    get,
    list_names,
    register,
    utc_from_millis,
)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
INST_ID = "XAAPL-USDT"
INST_TYPE = "SPOT"


# --------------------------------------------------------------------------- 端口契约


class MarketDataPortContract:
    """`MarketDataPort` 的行为契约，由实现方的测试类继承。

    子类覆写 `port` fixture 提供被测实现，并要求该实现能返回至少一根请求周期内的
    K 线、一条标的元数据和一个 ticker 快照。
    """

    @pytest.fixture
    def port(self) -> MarketDataPort:
        raise NotImplementedError("契约子类必须覆写 port fixture 提供被测实现")

    @pytest.fixture
    def timeframe(self) -> Timeframe:
        return Timeframe.parse("1h")

    def test_satisfies_runtime_protocol(self, port: MarketDataPort) -> None:
        assert isinstance(port, MarketDataPort)

    def test_instruments_carry_venue_metadata(self, port: MarketDataPort) -> None:
        instruments = port.instruments(INST_TYPE)

        assert instruments
        for item in instruments:
            assert isinstance(item, InstrumentRef)
            assert item.inst_id
            assert item.inst_type
            assert item.quote_ccy

    def test_unknown_category_raises(self, port: MarketDataPort, timeframe: Timeframe) -> None:
        """未登记的类别必须报错：不返回空结果，也不退回另一类的口径。"""

        with pytest.raises(ValidationError):
            port.instruments("FUTURES")
        with pytest.raises(ValidationError):
            port.candles(INST_ID, timeframe, inst_type="FUTURES")

    def test_candles_are_ascending_and_match_the_request(
        self, port: MarketDataPort, timeframe: Timeframe
    ) -> None:
        bars = port.candles(INST_ID, timeframe, inst_type=INST_TYPE, limit=100)

        assert bars
        assert all(isinstance(bar, Bar) for bar in bars)
        assert all(bar.inst_id == INST_ID for bar in bars)
        assert all(bar.timeframe == timeframe for bar in bars)
        assert [bar.open_time for bar in bars] == sorted(bar.open_time for bar in bars)

    def test_candles_respect_the_limit(self, port: MarketDataPort, timeframe: Timeframe) -> None:
        assert len(port.candles(INST_ID, timeframe, inst_type=INST_TYPE, limit=1)) <= 1

    def test_history_candles_stop_before_the_cursor(
        self, port: MarketDataPort, timeframe: Timeframe
    ) -> None:
        bars = port.history_candles(INST_ID, timeframe, inst_type=INST_TYPE)
        cursor = bars[-1].open_time

        older = port.history_candles(INST_ID, timeframe, inst_type=INST_TYPE, after=cursor)

        assert all(bar.open_time < cursor for bar in older)

    def test_ticker_snapshot_is_timezone_aware(self, port: MarketDataPort) -> None:
        snapshot = port.ticker(INST_ID, inst_type=INST_TYPE)

        assert isinstance(snapshot, Ticker)
        assert snapshot.inst_id == INST_ID
        assert snapshot.ts.tzinfo is not None

    def test_close_is_idempotent(self, port: MarketDataPort) -> None:
        port.close()
        port.close()


class TradePortContract:
    """`TradePort` 的行为契约。

    被测实现的 fixture 需要预先提供一笔成交记录，`fills` 的断言才有依据。
    """

    @pytest.fixture
    def port(self) -> TradePort:
        raise NotImplementedError("契约子类必须覆写 port fixture 提供被测实现")

    @pytest.fixture
    def intent(self) -> OrderIntent:
        return OrderIntent(
            inst_id=INST_ID,
            side="buy",
            qty=Decimal("2"),
            order_type="limit",
            price=Decimal("340.00"),
            client_order_id="contract-probe",
        )

    def test_satisfies_runtime_protocol(self, port: TradePort) -> None:
        assert isinstance(port, TradePort)

    def test_balance_is_money(self, port: TradePort) -> None:
        money = port.balance("USDT")

        assert isinstance(money, Money)
        assert money.currency == "USDT"
        assert isinstance(money.amount, Decimal)

    def test_positions_are_position_rows(self, port: TradePort) -> None:
        assert all(isinstance(row, Position) for row in port.positions())

    def test_place_returns_a_tracked_order(self, port: TradePort, intent: OrderIntent) -> None:
        order = port.place(intent)

        assert isinstance(order, Order)
        assert order.inst_id == intent.inst_id
        assert order.side == intent.side
        assert order.qty == intent.qty
        assert order.status
        assert port.order(intent.inst_id, order.order_id) == order

    def test_cancel_closes_an_open_order(self, port: TradePort, intent: OrderIntent) -> None:
        order = port.place(intent)

        port.cancel(order.inst_id, order.order_id)

        assert port.order(order.inst_id, order.order_id).status != "open"

    def test_cancel_rejects_unknown_order(self, port: TradePort) -> None:
        with pytest.raises(ExecutionRejected):
            port.cancel(INST_ID, "ord-not-found")

    def test_fills_are_scoped_to_the_instrument(self, port: TradePort) -> None:
        fills = port.fills(INST_ID)

        assert fills
        assert all(isinstance(row, Fill) for row in fills)
        assert all(row.inst_id == INST_ID for row in fills)

    def test_fills_filter_by_order(self, port: TradePort) -> None:
        fills = port.fills(INST_ID)
        order_id = fills[0].order_id

        rows = port.fills(INST_ID, order_id)

        assert [row.order_id for row in rows] == [
            row.order_id for row in fills if row.order_id == order_id
        ]


class TestInMemoryMarketDataContract(MarketDataPortContract):
    @pytest.fixture
    def port(self, market_port: MarketDataPort) -> MarketDataPort:
        return market_port


class TestInMemoryTradePortContract(TradePortContract):
    @pytest.fixture
    def port(self, trade_port: TradePort) -> TradePort:
        return trade_port


class _EmptyMarketData(MarketDataPort):
    """故意不覆写任何方法，用来验证「空实现调用即报错」。"""


class _EmptyTradePort(TradePort):
    """同上。"""


class _EmptyClock(Clock):
    """同上。"""


def test_empty_implementation_raises_on_every_port_method(
    one_hour: Timeframe,
) -> None:
    market = _EmptyMarketData()
    trade = _EmptyTradePort()

    assert issubclass(_EmptyMarketData, MarketDataPort)
    assert issubclass(_EmptyTradePort, TradePort)

    with pytest.raises(NotImplementedError):
        market.instruments(INST_TYPE)
    with pytest.raises(NotImplementedError):
        market.candles(INST_ID, one_hour, inst_type=INST_TYPE)
    with pytest.raises(NotImplementedError):
        market.history_candles(INST_ID, one_hour, inst_type=INST_TYPE)
    with pytest.raises(NotImplementedError):
        market.ticker(INST_ID, inst_type=INST_TYPE)
    with pytest.raises(NotImplementedError):
        market.close()

    with pytest.raises(NotImplementedError):
        trade.balance("USDT")
    with pytest.raises(NotImplementedError):
        trade.positions()
    with pytest.raises(NotImplementedError):
        trade.place(OrderIntent(inst_id=INST_ID, side="buy", qty=Decimal("1"), order_type="market"))
    with pytest.raises(NotImplementedError):
        trade.cancel(INST_ID, "ord-1")
    with pytest.raises(NotImplementedError):
        trade.order(INST_ID, "ord-1")
    with pytest.raises(NotImplementedError):
        trade.fills(INST_ID)


def test_empty_clock_raises() -> None:
    with pytest.raises(NotImplementedError):
        _EmptyClock().now()


# --------------------------------------------------------------------------- 值对象


def test_immutable_timeframe(one_hour: Timeframe) -> None:
    with pytest.raises(FrozenInstanceError):
        one_hour.value = "1d"


def test_immutable_money(usdt: Money) -> None:
    with pytest.raises(FrozenInstanceError):
        usdt.currency = "USDC"


def test_immutable_bar(bars: list[Bar]) -> None:
    with pytest.raises(FrozenInstanceError):
        bars[0].close = Decimal("1")


def test_immutable_instrument_ref(instrument: InstrumentRef) -> None:
    with pytest.raises(FrozenInstanceError):
        instrument.state = "suspend"


def test_immutable_ticker(snapshot: Ticker) -> None:
    with pytest.raises(FrozenInstanceError):
        snapshot.last = Decimal("1")


def test_immutable_signal() -> None:
    signal = Signal(inst_id=INST_ID, side="long", strength=0.6, ts=NOW)

    with pytest.raises(FrozenInstanceError):
        signal.side = "short"


def test_immutable_order_intent() -> None:
    intent = OrderIntent(inst_id=INST_ID, side="buy", qty=Decimal("1"), order_type="market")

    with pytest.raises(FrozenInstanceError):
        intent.qty = Decimal("2")


def test_immutable_order() -> None:
    order = Order(
        order_id="ord-1",
        client_order_id="c-1",
        inst_id=INST_ID,
        side="buy",
        order_type="limit",
        qty=Decimal("1"),
        price=Decimal("340.00"),
        filled_qty=Decimal("0"),
        status="open",
        ts=NOW,
    )

    with pytest.raises(FrozenInstanceError):
        order.status = "filled"


def test_immutable_fill(usdt: Money) -> None:
    fill = Fill(
        fill_id="fill-1",
        order_id="ord-1",
        inst_id=INST_ID,
        side="buy",
        qty=Decimal("1"),
        price=Decimal("340.00"),
        fee=usdt,
        ts=NOW,
    )

    with pytest.raises(FrozenInstanceError):
        fill.qty = Decimal("2")


def test_immutable_position(usdt: Money) -> None:
    position = Position(
        inst_id=INST_ID, qty=Decimal("1"), avg_price=Decimal("340.00"), unrealized_pnl=usdt
    )

    with pytest.raises(FrozenInstanceError):
        position.qty = Decimal("2")


def test_timeframe_parse_is_strict() -> None:
    assert Timeframe.parse("1h") == Timeframe("1h", 3600)

    for raw in ("1H", "60m", "2h", ""):
        with pytest.raises(ValidationError):
            Timeframe.parse(raw)


def test_timeframe_rejects_mismatched_seconds() -> None:
    with pytest.raises(ValidationError):
        Timeframe("1h", 60)


def test_timeframe_all_covers_the_supported_bars() -> None:
    assert [item.value for item in Timeframe.ALL] == [
        "1m",
        "5m",
        "15m",
        "1h",
        "4h",
        "1d",
    ]


def test_money_rejects_non_decimal_amount() -> None:
    with pytest.raises(ValidationError):
        Money(amount=1.5, currency="USDT")


def test_money_rejects_empty_currency() -> None:
    with pytest.raises(ValidationError):
        Money(amount=Decimal("1"), currency="")


def test_order_intent_requires_price_for_limit_order() -> None:
    with pytest.raises(ValidationError):
        OrderIntent(inst_id=INST_ID, side="buy", qty=Decimal("1"), order_type="limit")


def test_order_intent_rejects_price_for_market_order() -> None:
    with pytest.raises(ValidationError):
        OrderIntent(
            inst_id=INST_ID,
            side="buy",
            qty=Decimal("1"),
            order_type="market",
            price=Decimal("340.00"),
        )


def test_order_intent_rejects_non_positive_qty() -> None:
    with pytest.raises(ValidationError):
        OrderIntent(inst_id=INST_ID, side="buy", qty=Decimal("0"), order_type="market")


def test_order_intent_rejects_unknown_side() -> None:
    with pytest.raises(ValidationError):
        OrderIntent(inst_id=INST_ID, side="long", qty=Decimal("1"), order_type="market")


def test_signal_rejects_out_of_range_strength() -> None:
    with pytest.raises(ValidationError):
        Signal(inst_id=INST_ID, side="long", strength=1.5, ts=NOW)


# --------------------------------------------------------------------------- 错误体系


def test_error_hierarchy_is_closed() -> None:
    assert set(TradingError.__subclasses__()) == {
        ValidationError,
        UpstreamError,
        DataUnavailable,
        Conflict,
        RiskBlocked,
        ExecutionRejected,
        UnprocessableEntity,
        InvariantViolation,
    }


@pytest.mark.parametrize(
    ("error_type", "status"),
    [
        (ValidationError, 400),
        (UpstreamError, 502),
        (DataUnavailable, 503),
        (Conflict, 409),
        (RiskBlocked, 409),
        (ExecutionRejected, 422),
        (UnprocessableEntity, 422),
        (InvariantViolation, 500),
    ],
)
def test_error_maps_to_a_single_http_status(error_type: type[TradingError], status: int) -> None:
    assert error_type.http_status == status
    assert issubclass(error_type, TradingError)


def test_risk_blocked_carries_rule_and_detail() -> None:
    error = RiskBlocked(rule="max-drawdown", detail="回撤超过 10%")

    assert (error.rule, error.detail) == ("max-drawdown", "回撤超过 10%")
    assert "max-drawdown" in str(error)


# --------------------------------------------------------------------------- registry


class _Probe:
    """登记用的标记对象。"""


def test_registry_register_get_and_list() -> None:
    kind = "contract-probe-basic"
    alpha = _Probe()

    assert register(kind, "alpha")(alpha) is alpha
    _ = register(kind, "beta")(_Probe())

    assert get(kind, "alpha") is alpha
    assert list_names(kind) == ["alpha", "beta"]


def test_registry_rejects_duplicate_registration() -> None:
    kind = "contract-probe-duplicate"
    _ = register(kind, "same")(_Probe())

    with pytest.raises(InvariantViolation, match="重复登记"):
        register(kind, "same")(_Probe())


def test_registry_unknown_name_reports_available_ones() -> None:
    kind = "contract-probe-missing"
    _ = register(kind, "present")(_Probe())

    with pytest.raises(ValidationError, match="present"):
        get(kind, "absent")


def test_registry_list_unknown_kind_is_empty() -> None:
    assert list_names("contract-probe-never-registered") == []


# --------------------------------------------------------------------------- clock


def test_system_clock_returns_aware_utc() -> None:
    now = SystemClock().now()

    assert now.utcoffset() == timedelta(0)
    assert abs(datetime.now(UTC) - now) < timedelta(seconds=5)


def test_replay_clock_advances_monotonically() -> None:
    clock = ReplayClock(NOW)
    assert isinstance(clock, Clock)

    clock.advance_to(NOW + timedelta(hours=1))

    assert clock.now() == NOW + timedelta(hours=1)


def test_replay_clock_rejects_backwards_move() -> None:
    clock = ReplayClock(NOW + timedelta(hours=1))

    with pytest.raises(ValidationError, match="倒退"):
        clock.advance_to(NOW)


def test_replay_clock_rejects_naive_start() -> None:
    with pytest.raises(ValidationError):
        ReplayClock(datetime(2026, 11, 10))


def test_utc_from_millis_returns_aware_datetime() -> None:
    expected = datetime.fromtimestamp(1794290400, tz=UTC)

    assert utc_from_millis("1794290400000") == expected
    assert utc_from_millis(1794290400000) == expected

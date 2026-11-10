"""契约测试的装配。

契约测试要能被任意实现复用：内存实现、真实 OKX 适配器、以后的 `us_equity`
provider 都继承同一组契约类。这里是「实现」的一方——两个只满足端口签名的内存实现，
以及它们需要的构造数据。

构造数据只允许出现在 `tests/`；`app/` 内不允许任何 mock 常量，这条由
`tests/architecture/test_no_mock_in_app.py` 把关。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core import (
    Bar,
    DataUnavailable,
    ExecutionRejected,
    Fill,
    InstrumentRef,
    MarketDataPort,
    Money,
    Order,
    OrderIntent,
    Position,
    Ticker,
    Timeframe,
    TradePort,
)

#: 测试内部使用的时间点，避免依赖真实时钟。
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


class InMemoryMarketData(MarketDataPort):
    """只实现端口语义的内存行情，不模拟任何交易所行为。"""

    def __init__(
        self,
        *,
        instruments: list[InstrumentRef],
        bars: list[Bar],
        snapshot: Ticker,
    ) -> None:
        self.closed = False
        self._instruments = list(instruments)
        self._bars = list(bars)
        self._snapshot = snapshot

    def instruments(self) -> list[InstrumentRef]:
        return list(self._instruments)

    def candles(self, inst_id: str, timeframe: Timeframe, *, limit: int = 100) -> list[Bar]:
        return self._select(inst_id, timeframe)[-limit:]

    def history_candles(
        self,
        inst_id: str,
        timeframe: Timeframe,
        *,
        after: datetime | None = None,
        limit: int = 100,
    ) -> list[Bar]:
        bars = self._select(inst_id, timeframe)
        if after is not None:
            bars = [bar for bar in bars if bar.open_time < after]
        return bars[-limit:]

    def ticker(self, inst_id: str) -> Ticker:
        if inst_id != self._snapshot.inst_id:
            raise DataUnavailable(f"没有 {inst_id} 的行情快照")
        return self._snapshot

    def close(self) -> None:
        self.closed = True

    def _select(self, inst_id: str, timeframe: Timeframe) -> list[Bar]:
        return [bar for bar in self._bars if bar.inst_id == inst_id and bar.timeframe == timeframe]


class InMemoryTradePort(TradePort):
    """只实现端口语义的内存交易通道，订单状态机只够契约使用。"""

    def __init__(self, *, balance: Money) -> None:
        self._balance = balance
        self._orders: dict[str, Order] = {}
        self._fills: dict[str, list[Fill]] = {}
        self._positions: list[Position] = []
        self._sequence = 0

    def balance(self, currency: str = "USDT") -> Money:
        if currency != self._balance.currency:
            raise DataUnavailable(f"账户没有 {currency} 余额")
        return self._balance

    def positions(self) -> list[Position]:
        return list(self._positions)

    def place(self, intent: OrderIntent) -> Order:
        self._sequence += 1
        order = Order(
            order_id=f"ord-{self._sequence}",
            client_order_id=intent.client_order_id,
            inst_id=intent.inst_id,
            side=intent.side,
            order_type=intent.order_type,
            qty=intent.qty,
            price=intent.price,
            filled_qty=Decimal("0"),
            status="open",
            ts=NOW,
        )
        self._orders[order.order_id] = order
        return order

    def cancel(self, inst_id: str, order_id: str) -> None:
        order = self._require(inst_id, order_id)
        if order.status != "open":
            raise ExecutionRejected(f"订单 {order_id} 已是 {order.status}; 不能撤单")
        self._orders[order_id] = replace(order, status="canceled")

    def order(self, inst_id: str, order_id: str) -> Order:
        return self._require(inst_id, order_id)

    def fills(self, inst_id: str, order_id: str | None = None) -> list[Fill]:
        rows = self._fills.get(inst_id, [])
        if order_id is None:
            return list(rows)
        return [row for row in rows if row.order_id == order_id]

    def record_fill(self, fill: Fill) -> None:
        """测试专用的成交注入点，不属于端口契约。"""

        self._fills.setdefault(fill.inst_id, []).append(fill)

    def _require(self, inst_id: str, order_id: str) -> Order:
        order = self._orders.get(order_id)
        if order is None or order.inst_id != inst_id:
            raise ExecutionRejected(f"订单不存在: {inst_id}/{order_id}")
        return order


@pytest.fixture
def one_hour() -> Timeframe:
    return Timeframe.parse("1h")


@pytest.fixture
def instrument() -> InstrumentRef:
    return InstrumentRef(
        inst_id="XAAPL-USDT",
        inst_type="SPOT",
        base_ccy="AAPL",
        quote_ccy="USDT",
        state="live",
        inst_category="3",
        tick_size=Decimal("0.01"),
        lot_size=Decimal("0.001"),
        min_size=Decimal("0.01"),
        list_time=datetime(2025, 10, 9, 4, 0, tzinfo=UTC),
    )


@pytest.fixture
def bars(one_hour: Timeframe) -> list[Bar]:
    """三根按时间升序、逐根上涨的 1h K 线。"""

    closes = ("351.00", "352.11", "353.40")
    rows: list[Bar] = []
    for index, close in enumerate(closes):
        open_time = datetime(2026, 11, 10, 9 + index, tzinfo=UTC)
        rows.append(
            Bar(
                inst_id="XAAPL-USDT",
                timeframe=one_hour,
                open_time=open_time,
                open=Decimal(close),
                high=Decimal(close),
                low=Decimal(close),
                close=Decimal(close),
                volume=Decimal("10"),
                confirm=True,
                source="in-memory",
            )
        )
    return rows


@pytest.fixture
def snapshot() -> Ticker:
    return Ticker(
        inst_id="XAAPL-USDT",
        last=Decimal("353.40"),
        bid=Decimal("353.39"),
        ask=Decimal("353.41"),
        volume_24h=Decimal("1234.5"),
        ts=NOW,
    )


@pytest.fixture
def usdt() -> Money:
    return Money(amount=Decimal("1000"), currency="USDT")


@pytest.fixture
def market_port(instrument: InstrumentRef, bars: list[Bar], snapshot: Ticker) -> InMemoryMarketData:
    return InMemoryMarketData(instruments=[instrument], bars=bars, snapshot=snapshot)


@pytest.fixture
def trade_port(usdt: Money) -> InMemoryTradePort:
    """已预置「一条订单 + 一笔成交」的交易通道，供契约断言使用。"""

    port = InMemoryTradePort(balance=usdt)
    order = port.place(
        OrderIntent(
            inst_id="XAAPL-USDT",
            side="buy",
            qty=Decimal("1"),
            order_type="limit",
            price=Decimal("340.00"),
            client_order_id="seeded",
        )
    )
    port.record_fill(
        Fill(
            fill_id="fill-1",
            order_id=order.order_id,
            inst_id=order.inst_id,
            side=order.side,
            qty=order.qty,
            price=Decimal("340.00"),
            fee=Money(amount=Decimal("0.34"), currency="USDT"),
            ts=NOW,
        )
    )
    return port

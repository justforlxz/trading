"""Phase 5 端到端：信号 → 计划 → 确认 → 下单 → 成交 → 持仓 → journal 可查。

链路前半段（策略实例、回测预期）走 HTTP 与业务写入路径；后半段走真实的 paper
撮合与执行编排，再把执行事实交给 journal 读取。全程不联网：行情来自本地落库，
paper 账本不调用假 OKX 的任何交易端点。

只读性用行数比对断言：读取 journal 前后，journal 读到的表行数必须完全一致。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import Bar, InstrumentRef, Signal, Timeframe
from app.db import session_scope
from app.execution import (
    ExecutionService,
    PaperBroker,
    build_plan,
    client_order_id,
    paper_snapshot,
)
from app.instrument import Instrument, list_instruments, sync_instruments
from app.journal import ExecutionSnapshot, RecordedSignal, latest_expectations, load_journal
from app.market import upsert_candles
from app.strategy import TargetLeg, TargetPortfolio, get_instance
from tests.factories.instruments import make_ref

INST_IDS = ("BTC-USDT", "ETH-USDT")
BTC = "BTC-USDT"
BTC_PRICE = Decimal("105")
SELL_PRICE = Decimal("110")
AMOUNT_BOUGHT = Decimal("4.76190")
AMOUNT_SOLD = Decimal("2")
AS_OF = datetime(2026, 11, 10, 23, 0, tzinfo=UTC)
CLOSES = {
    "BTC-USDT": ["100", "101", "102", "103", "104", "105", "106", "107", "108", "109"],
    "ETH-USDT": ["50", "51", "52", "53", "55", "58", "60", "61", "62", "63"],
}
JOURNAL_TABLES = (
    "strategy_instances",
    "strategy_templates",
    "strategy_replays",
    "strategy_approvals",
    "backtest_runs",
    "backtest_trades",
    "backtest_equity",
    "order_submissions",
)
QUANTUM = Decimal("0.000000000001")


class MutablePaperBackend:
    """paper 后端的一层薄包装：行情价可以在同一用例里移动，撮合仍走 `PaperBroker`。"""

    def __init__(self, broker: PaperBroker, *, instruments, prices) -> None:
        self._broker = broker
        self._instruments = instruments
        self.prices = dict(prices)

    def place(self, intent, *, now):
        instrument = self._instruments[intent.inst_id]
        return self._broker.place(
            intent,
            instrument,
            market_price=self.prices[intent.inst_id],
            now=now,
        )


def seed_market() -> None:
    """标的与日线都走生产写入路径，形状与真实同步一致。"""

    sync_instruments(
        [
            make_ref(inst_id=inst_id, base_ccy=inst_id.split("-")[0], inst_category="1")
            for inst_id in INST_IDS
        ]
    )
    for inst_id in INST_IDS:
        closes = CLOSES[inst_id]
        upsert_candles(
            [
                Bar(
                    inst_id=inst_id,
                    timeframe=Timeframe.parse("1d"),
                    open_time=AS_OF - timedelta(days=len(closes) - 1 - index),
                    open=Decimal(close),
                    high=Decimal(close),
                    low=Decimal(close),
                    close=Decimal(close),
                    volume=Decimal("10"),
                    confirm=True,
                    source="okx_spot",
                )
                for index, close in enumerate(closes)
            ]
        )


def create_instance(client: TestClient) -> str:
    created = client.post(
        "/api/strategy-instances",
        json={
            "strategy_id": "relative_value",
            "name": "BTC/ETH 相对价值",
            "bar": "1d",
            "params": {"reversion_window": 3, "strength_window": 2, "pair_count": 1},
            "inst_ids": list(INST_IDS),
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["instance_id"]


def run_backtest(client: TestClient, instance_id: str) -> None:
    """跑一次真实回测，给 journal 提供「预期收益」的来源行。"""

    response = client.post(
        "/api/backtests",
        json={
            "strategy_instance_id": instance_id,
            "targets": {"mode": "list", "inst_ids": list(INST_IDS), "group": None},
            "bar": "1d",
            "start_date": (AS_OF.date() - timedelta(days=9)).isoformat(),
            "end_date": AS_OF.date().isoformat(),
            "initial_capital": "10000",
            "quote_currency": "USDT",
            "position_size": "10000",
            "max_position_pct": "1",
            "costs": {
                "maker_fee_bps": "2",
                "taker_fee_bps": "10",
                "slippage_bps": "5",
                "spread_bps": "2",
            },
            "funding_enabled": True,
            "execution_model": "next_open",
            "data_source": "okx_spot",
        },
    )
    assert response.status_code == 202, response.text


def instrument_ref(row: Instrument) -> InstrumentRef:
    """标的行 → 策略层用的最小引用，只带数量换算需要的字段。"""

    return InstrumentRef(
        inst_id=row.symbol,
        inst_type=row.inst_type,
        base_ccy=row.base_currency,
        quote_ccy=row.quote_currency,
        state=row.trading_status,
        tick_size=row.tick_size,
        lot_size=row.lot_size,
        min_size=row.min_order_size,
        ct_val_ccy=row.product_key,
        settle_ccy=row.settle_ccy or "",
        ct_val=row.ct_val,
        ct_mult=row.ct_mult,
        max_lever=row.max_lever,
    )


def build_paper_chain(instance_id: str):
    """真实 paper 链路：买入一部分，再卖掉一部分，留下一笔已实现盈亏与一条持仓。"""

    instruments = {row.symbol: row for row in list_instruments()}
    btc = instruments[BTC]
    refs = {row.product_key: instrument_ref(row) for row in instruments.values()}
    broker = PaperBroker(fee_rate=Decimal("0"), slippage=Decimal("0"))
    backend = MutablePaperBackend(
        broker,
        instruments={BTC: btc},
        prices={BTC: BTC_PRICE},
    )
    service = ExecutionService(backend)

    buy = build_plan(
        plan_id="plan-buy",
        version=1,
        strategy_id=instance_id,
        target=TargetPortfolio(
            as_of=AS_OF,
            legs=(TargetLeg(product_key="BTC", side="long", target_weight=Decimal("0.5")),),
        ),
        signals=(Signal(inst_id=BTC, side="long", strength=0.8, ts=AS_OF, reason="测试信号"),),
        instruments=refs,
        prices={BTC: BTC_PRICE},
        capital=Decimal("1000"),
    )
    service.confirm(buy, confirmed_by="lxz")
    service.place(buy)

    backend.prices[BTC] = SELL_PRICE
    sell = build_plan(
        plan_id="plan-sell",
        version=2,
        strategy_id=instance_id,
        target=TargetPortfolio(
            as_of=AS_OF,
            legs=(TargetLeg(product_key="BTC", side="short", target_weight=Decimal("0.5")),),
        ),
        signals=(Signal(inst_id=BTC, side="short", strength=0.8, ts=AS_OF, reason="测试平仓"),),
        instruments=refs,
        prices={BTC: SELL_PRICE},
        capital=Decimal("440"),
    )
    service.confirm(sell, confirmed_by="lxz")
    service.place(sell)
    service.sync(paper_snapshot(broker))

    owners = {
        client_order_id(buy, buy.legs[0]): instance_id,
        client_order_id(sell, sell.legs[0]): instance_id,
    }
    snapshot = ExecutionSnapshot(
        mode="paper",
        orders=service.state.orders,
        fills=service.state.fills,
        positions=service.state.positions,
        signals=(
            RecordedSignal(
                signal_id="sig-1",
                instance_id=instance_id,
                inst_id=BTC,
                inst_type="SPOT",
                side="long",
                strength=0.8,
                price=BTC_PRICE,
                reason="测试信号",
                generated_at=AS_OF,
            ),
        ),
        order_owners=owners,
    )
    return snapshot


def table_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    with session_scope() as session:
        for table in JOURNAL_TABLES:
            counts[table] = int(session.scalar(text(f'SELECT count(*) FROM "{table}"')) or 0)
    return counts


@pytest.fixture()
def journal_client(client: TestClient) -> Iterator[tuple[TestClient, str]]:
    seed_market()
    instance_id = create_instance(client)
    run_backtest(client, instance_id)
    snapshot = build_paper_chain(instance_id)
    client.app.state.execution_snapshot = snapshot
    try:
        yield client, instance_id
    finally:
        client.app.state.execution_snapshot = ExecutionSnapshot()


def test_phase5_signal_to_journal(journal_client: tuple[TestClient, str]) -> None:
    """全链路走完：journal 同时报出回测预期与实际成交，并且不改动任何表。"""

    client, instance_id = journal_client
    before = table_counts()

    view = load_journal(snapshot=client.app.state.execution_snapshot)
    assert view is not None
    assert view.mode == "paper"

    strategy = next(item for item in view.strategies if item.instance_id == instance_id)
    assert strategy.expected_return is not None
    assert strategy.expected_source.startswith("backtest:")
    assert strategy.expected_source.endswith(":metrics.total_return")
    assert strategy.actual_source == "execution:fills:2"
    assert strategy.fill_count == 2
    assert strategy.expected_source != strategy.actual_source

    expected_actual = Decimal("10") / Decimal("210")
    assert abs(strategy.actual_return - expected_actual) < QUANTUM
    assert strategy.expected_return != strategy.actual_return

    positions = view.positions
    assert len(positions) == 1
    assert positions[0].product_key == "BTC"
    assert positions[0].qty == AMOUNT_BOUGHT - AMOUNT_SOLD

    assert [order.side for order in view.orders] == ["buy", "sell"]
    assert [fill.side for fill in view.fills] == ["buy", "sell"]
    assert view.signals[0].instance_id == instance_id
    categories = {entry.category for entry in view.entries}
    assert {"signal", "order", "fill"} <= categories

    # 预期来源可以回到具体运行：读库确认最新一次回测就是报出的那一条。
    record = get_instance(instance_id)
    assert record is not None
    sourced = latest_expectations([record])[instance_id]
    assert sourced[1] == strategy.expected_source

    assert table_counts() == before

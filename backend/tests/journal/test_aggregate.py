"""journal 的纯函数：FIFO 已实现收益、两个来源与日志条目。

所有数值都用手算的已知答案断言，不依赖数据库或行情。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core import Fill, Money
from app.execution import Order
from app.journal import (
    ExecutionSnapshot,
    RecordedSignal,
    build_journal,
    build_strategy_journal,
    realized_summary,
)
from app.strategy import InstanceRecord

NOW = datetime(2026, 11, 12, 3, 0, 0, tzinfo=UTC)
INST = "XAAPL-USDT"


def _instance() -> InstanceRecord:
    return InstanceRecord(
        instance_id="si-1",
        strategy_id="relative_value",
        strategy_version="1.0.0",
        name="AAPL 相对价值",
        bar="1h",
        params={"reversion_window": 20},
        inst_ids=(INST,),
        lifecycle_status="paper_trading",
        enabled=True,
        execution_mode="paper",
        latest_signal_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _fill(
    *,
    fill_id: str,
    side: str,
    qty: str,
    price: str,
    fee: str = "0",
    minute: int,
    inst_id: str = INST,
) -> Fill:
    return Fill(
        fill_id=fill_id,
        order_id="ord-1",
        inst_id=inst_id,
        side=side,
        qty=Decimal(qty),
        price=Decimal(price),
        fee=Money(Decimal(fee), "USDT"),
        ts=NOW + timedelta(minutes=minute),
    )


def _order(*, client_order_id: str = "cli-1", order_id: str = "ord-1") -> Order:
    return Order(
        client_order_id=client_order_id,
        order_id=order_id,
        inst_id=INST,
        side="buy",
        order_type="market",
        qty=Decimal("2"),
        price=None,
        created_at=NOW,
        updated_at=NOW,
        status="filled",
        filled_qty=Decimal("2"),
        filled_cost=Decimal("200"),
    )


def test_realized_summary_matches_known_round_trip() -> None:
    """买 2 手 100、卖 2 手 110：已实现 20，成本 200，收益率 0.1。"""

    summary = realized_summary(
        [
            _fill(fill_id="f1", side="buy", qty="2", price="100", minute=0),
            _fill(fill_id="f2", side="sell", qty="2", price="110", minute=5),
        ]
    )

    assert summary.realized_pnl == Decimal("20.000000000000")
    assert summary.cost_basis == Decimal("200.000000000000")
    assert summary.realized_return == Decimal("0.100000000000")
    assert summary.net_cash_flow == Decimal("20.000000000000")
    # 资金变化按成交顺序：先付出 200，再收回 220。
    assert [point.amount for point in summary.cash_flow] == [
        Decimal("-200"),
        Decimal("220"),
    ]
    assert [point.value for point in summary.curve] == [Decimal("0.100000000000")]


def test_realized_summary_only_closes_part_of_the_position() -> None:
    """买 4 手 100、卖 2 手 120：只把卖出的 2 手算作已实现，剩余 2 手留在持仓。"""

    summary = realized_summary(
        [
            _fill(fill_id="f1", side="buy", qty="4", price="100", minute=0),
            _fill(fill_id="f2", side="sell", qty="2", price="120", minute=5),
        ]
    )

    assert summary.realized_pnl == Decimal("40.000000000000")
    assert summary.cost_basis == Decimal("200.000000000000")
    assert summary.realized_return == Decimal("0.200000000000")


def test_realized_summary_handles_short_round_trip() -> None:
    """先卖后买：卖 1 手 100、买 1 手 90，已实现 10，成本 100。"""

    summary = realized_summary(
        [
            _fill(fill_id="f1", side="sell", qty="1", price="100", minute=0),
            _fill(fill_id="f2", side="buy", qty="1", price="90", minute=5),
        ]
    )

    assert summary.realized_pnl == Decimal("10.000000000000")
    assert summary.cost_basis == Decimal("100.000000000000")
    assert summary.realized_return == Decimal("0.100000000000")


def test_open_and_close_fees_enter_realized_pnl() -> None:
    """开仓费按成交量摊进成本，平仓费从盈利里扣：20 - 2 - 2 = 16。"""

    summary = realized_summary(
        [
            _fill(fill_id="f1", side="buy", qty="2", price="100", fee="2", minute=0),
            _fill(fill_id="f2", side="sell", qty="2", price="110", fee="2", minute=5),
        ]
    )

    assert summary.realized_pnl == Decimal("16.000000000000")
    assert summary.cost_basis == Decimal("200.000000000000")
    assert summary.realized_return == Decimal("0.080000000000")
    # 卖出收回的是成交额减手续费：220 - 2 = 218，与买入付出的 202 相加正好是 16。
    assert [point.amount for point in summary.cash_flow] == [
        Decimal("-202"),
        Decimal("218"),
    ]
    assert summary.net_cash_flow == summary.realized_pnl


def test_fifo_pairs_fills_within_the_same_instrument() -> None:
    """先买 BTC、再买 ETH、然后卖 ETH：只能平 ETH 的批次，不能拿 BTC 的持仓顶替。"""

    eth = "ETH-USDT"
    summary = realized_summary(
        [
            _fill(fill_id="f1", side="buy", qty="1", price="100", minute=0),
            _fill(fill_id="f2", side="buy", qty="1", price="50", minute=1, inst_id=eth),
            _fill(fill_id="f3", side="sell", qty="1", price="60", minute=2, inst_id=eth),
        ]
    )

    assert summary.realized_pnl == Decimal("10.000000000000")
    assert summary.cost_basis == Decimal("50.000000000000")
    assert summary.realized_return == Decimal("0.200000000000")


def test_selling_without_a_matching_lot_opens_a_short_for_that_instrument() -> None:
    """只有 BTC 多头时卖出 ETH，不会平掉 BTC；这笔卖出只开出一个 ETH 空头批次。"""

    summary = realized_summary(
        [
            _fill(fill_id="f1", side="buy", qty="1", price="100", minute=0),
            _fill(fill_id="f2", side="sell", qty="1", price="150", minute=1, inst_id="ETH-USDT"),
        ]
    )

    assert summary.realized_pnl == Decimal("0E-12")
    assert summary.cost_basis == Decimal("0E-12")
    assert summary.realized_return == Decimal("0E-12")
    assert summary.net_cash_flow == Decimal("50")


def test_expected_and_actual_returns_have_separate_sources() -> None:
    """预期收益来自回测运行，实际收益来自成交；两者不互相回退填充。"""

    snapshot = ExecutionSnapshot(
        mode="paper",
        orders=(_order(),),
        fills=(
            _fill(fill_id="f1", side="buy", qty="2", price="100", minute=0),
            _fill(fill_id="f2", side="sell", qty="2", price="110", minute=5),
        ),
        order_owners={"cli-1": "si-1"},
    )
    journal = build_strategy_journal(
        _instance(),
        expected_return=Decimal("0.0525"),
        expected_source="backtest:bt-1:metrics.total_return",
        snapshot=snapshot,
    )

    assert journal.expected_return == Decimal("0.052500000000")
    assert journal.actual_return == Decimal("0.100000000000")
    assert journal.expected_source == "backtest:bt-1:metrics.total_return"
    assert journal.actual_source == "execution:fills:2"
    assert journal.expected_source != journal.actual_source
    assert journal.fill_count == 2


def test_missing_backtest_does_not_borrow_the_actual_value() -> None:
    """没有回测时预期收益为 None、来源写明没有，绝不拿实际收益顶上。"""

    snapshot = ExecutionSnapshot(
        mode="paper",
        orders=(_order(),),
        fills=(_fill(fill_id="f1", side="buy", qty="2", price="100", minute=0),),
        order_owners={"cli-1": "si-1"},
    )
    journal = build_strategy_journal(
        _instance(),
        expected_return=None,
        expected_source="backtest:none",
        snapshot=snapshot,
    )

    assert journal.expected_return is None
    assert journal.expected_source == "backtest:none"
    assert journal.actual_return == Decimal("0E-12")
    assert journal.actual_source == "execution:fills:1"


def test_journal_entries_are_derived_from_facts() -> None:
    """日志条目覆盖信号、订单与成交，按时间倒序排列。"""

    snapshot = ExecutionSnapshot(
        mode="paper",
        orders=(_order(),),
        fills=(
            _fill(fill_id="f1", side="buy", qty="2", price="100", minute=0),
            _fill(fill_id="f2", side="sell", qty="2", price="110", minute=5),
        ),
        signals=(
            RecordedSignal(
                signal_id="sig-1",
                instance_id="si-1",
                inst_id=INST,
                inst_type="SPOT",
                side="long",
                strength=0.8,
                price=Decimal("100"),
                reason="MA20 上穿 MA60",
                generated_at=NOW,
            ),
        ),
        order_owners={"cli-1": "si-1"},
    )

    view = build_journal((_instance(),), {"si-1": (Decimal("0.01"), "backtest:bt-1:x")}, snapshot)

    categories = [entry.category for entry in view.entries]
    assert categories.count("signal") == 1
    assert categories.count("order") == 1
    assert categories.count("fill") == 2
    times = [entry.created_at for entry in view.entries]
    assert times == sorted(times, reverse=True)

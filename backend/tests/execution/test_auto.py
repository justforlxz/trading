"""T6.2 自动执行：目标组合求差、取整跳过、风控在前、默认关闭、暂停与同步后求差。

判据来源（MKACG-735）：

- 当前 100 目标 150 → 买 50；当前 150 目标 100 → 卖 50；相等不产生订单。
- 增量按 lot_size 取整后不足最小下单量时不下单，跳过记录带 product_key 与原因。
- 风控拒绝时一个 OrderIntent 都不产生，`risk_events` 有记录。
- 未显式开启时循环不产生订单；开启/暂停状态变化有记录。
- 全局暂停后下一轮不产生新订单，已有持仓不动。
- 同一 as_of 的同一目标组合重复喂入只产生一批订单。
- 下一轮求差基于同步后的实际持仓，不基于本地预期；用假 OKX server 跑端到端。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core import InstrumentRef, OrderIntent, ReplayClock
from app.exchange import create_trade_port
from app.execution import (
    ACTION_DISABLE,
    ACTION_ENABLE,
    ACTION_PAUSE,
    ACTION_RESUME,
    AUTO_STATUS_DISABLED,
    AUTO_STATUS_DUPLICATE,
    AUTO_STATUS_EXECUTED,
    AUTO_STATUS_PAUSED,
    RUNTIME_PAUSED,
    RUNTIME_RUNNING,
    RUNTIME_STOPPED,
    STATUS_FILLED,
    AccountPosition,
    AutoExecutor,
    AutoRunResult,
    AutoRuntime,
    PositionDelta,
    RebalancePlan,
    RuntimeEvent,
    SkipRecord,
    TradePortBackend,
    accept,
    from_venue_position,
    new_order,
    reconcile_target,
    target_key,
)
from app.instrument import list_instruments, sync_instruments
from app.risk import (
    RiskContext,
    RiskEngine,
    RiskLimits,
    list_risk_events,
)
from app.strategy import TargetLeg, TargetPortfolio
from tests.execution.conftest import PRODUCT_KEY, SPOT_INST_ID
from tests.factories.instruments import make_ref
from tests.fakes.okx.server import FakeOkxServer

D = Decimal
NOW = datetime(2026, 11, 13, 2, 0, tzinfo=UTC)
INSTANCE = "si-1"


def spot_ref(
    *,
    lot_size: str = "0.001",
    min_size: str = "0.001",
    inst_type: str = "SPOT",
    inst_id: str = SPOT_INST_ID,
) -> InstrumentRef:
    """本文件用的标的快照：精度可调，默认与手算用例一致。"""

    return InstrumentRef(
        inst_id=inst_id,
        inst_type=inst_type,
        base_ccy="XAAPL",
        quote_ccy="USDT",
        state="live",
        tick_size=D("0.01"),
        lot_size=D(lot_size),
        min_size=D(min_size),
    )


def make_target(
    *,
    weight: str = "0.15",
    side: str = "long",
    as_of: datetime = NOW,
) -> TargetPortfolio:
    return TargetPortfolio(
        as_of=as_of,
        legs=(TargetLeg(product_key=PRODUCT_KEY, side=side, target_weight=D(weight)),),
    )


def account(
    qty: str = "100",
    *,
    side: str = "long",
    inst_type: str = "SPOT",
) -> AccountPosition:
    return AccountPosition(
        product_key=PRODUCT_KEY,
        inst_type=inst_type,
        side=side,
        qty=D(qty),
        avg_cost=D("90"),
    )


def generous_limits() -> RiskLimits:
    """把限额放宽到只用于验证流程；风控规则本身由 tests/risk 覆盖。"""

    return RiskLimits(
        max_order_ratio=D("10"),
        max_instrument_weight=D("10"),
        max_gross_exposure=D("10"),
        max_abs_net_exposure=D("10"),
        max_concentration=D("10"),
        max_correlated_weight=D("10"),
    )


def risk_context(*, equity: str = "100000") -> RiskContext:
    return RiskContext(
        equity=D(equity),
        strategy_equity=D(equity),
        available_balance=D(equity),
    )


class RecordingBackend:
    """记录每次下单意图的假后端；订单停在 open，不撮合。"""

    def __init__(self) -> None:
        self.intents: list[OrderIntent] = []

    def place(self, intent: OrderIntent, *, now: datetime):
        self.intents.append(intent)
        return accept(new_order(intent, now=now), f"stub{len(self.intents)}", now=now)


def reconcile(
    *,
    target: TargetPortfolio,
    positions: tuple[AccountPosition, ...],
    instrument: InstrumentRef | None = None,
    price: str = "100",
    capital: str = "100000",
) -> RebalancePlan:
    ref = instrument or spot_ref()
    return reconcile_target(
        instance_id=INSTANCE,
        target=target,
        positions=positions,
        instruments={PRODUCT_KEY: ref},
        prices={ref.inst_id: D(price)},
        capital=D(capital),
    )


# ------------------------------------------------------------------ 求差正确


def test_reconcile_buys_the_difference() -> None:
    """当前 100 股、目标 150 股 → 增量买入 50。"""

    plan = reconcile(target=make_target(weight="0.15"), positions=(account("100"),))

    assert isinstance(plan, RebalancePlan)
    assert plan.skipped == ()
    (delta,) = plan.deltas
    assert isinstance(delta, PositionDelta)
    assert (delta.side, delta.qty) == ("buy", D("50"))


def test_reconcile_sells_the_difference() -> None:
    """当前 150 股、目标 100 股 → 增量卖出 50。"""

    plan = reconcile(target=make_target(weight="0.10"), positions=(account("150"),))

    (delta,) = plan.deltas
    assert (delta.side, delta.qty) == ("sell", D("50"))


def test_reconcile_produces_no_order_when_already_at_target() -> None:
    """当前 100 股、目标 100 股 → 不产生订单（不是产生 0 量订单）。"""

    plan = reconcile(target=make_target(weight="0.10"), positions=(account("100"),))

    assert plan.deltas == ()
    assert plan.skipped == ()


# ------------------------------------------------------------------ 取整跳过


def test_increment_below_minimum_is_skipped_with_a_reason() -> None:
    """目标 100.0005、当前 100 → 增量 0.0005，低于最小下单量 0.001，跳过并记录。"""

    plan = reconcile(
        target=make_target(weight="0.1000005"),
        positions=(account("100"),),
        instrument=spot_ref(lot_size="0.0001", min_size="0.001"),
    )

    assert plan.deltas == ()
    (skip,) = plan.skipped
    assert isinstance(skip, SkipRecord)
    assert skip.product_key == PRODUCT_KEY
    assert "最小下单量" in skip.reason


# ------------------------------------------------------------------ 风控在前


def test_risk_rejection_produces_no_intent_and_records_events(client: TestClient) -> None:
    """必然被风控拒绝的目标组合：一个 OrderIntent 都没有，risk_events 有记录。"""

    sync_instruments([make_ref()])
    backend = RecordingBackend()
    runtime = AutoRuntime(clock=ReplayClock(NOW))
    runtime.enable(actor="tester")
    executor = AutoExecutor(
        backend=backend,
        risk=RiskEngine(),
        runtime=runtime,
        positions_provider=lambda: (),
        clock=ReplayClock(NOW),
    )

    result = executor.run(
        instance_id=INSTANCE,
        target=make_target(weight="0.10"),
        instruments={PRODUCT_KEY: spot_ref()},
        prices={SPOT_INST_ID: D("100")},
        capital=D("100000"),
        risk_context=risk_context(equity="1000"),
    )

    assert result.status == AUTO_STATUS_EXECUTED
    assert result.intents == ()
    assert result.placements == ()
    assert result.rejections
    assert backend.intents == []

    rows, total = list_risk_events(instance_id=INSTANCE)
    assert total > 0
    assert {row.rule for row in rows} >= {"order_amount_ratio", "available_balance"}


# ------------------------------------------------------------------ 默认关闭与状态记录


def test_default_off_produces_no_orders_and_records_enable(client: TestClient) -> None:
    sync_instruments([make_ref()])
    backend = RecordingBackend()
    runtime = AutoRuntime(clock=ReplayClock(NOW))
    executor = AutoExecutor(
        backend=backend,
        risk=RiskEngine(generous_limits()),
        runtime=runtime,
        clock=ReplayClock(NOW),
    )
    arguments = dict(
        instance_id=INSTANCE,
        target=make_target(weight="0.5"),
        instruments={PRODUCT_KEY: spot_ref()},
        prices={SPOT_INST_ID: D("100")},
        capital=D("1000"),
        risk_context=risk_context(),
    )

    closed = executor.run(**arguments)

    assert isinstance(closed, AutoRunResult)
    assert closed.status == AUTO_STATUS_DISABLED
    assert backend.intents == []
    assert runtime.events == ()

    event = runtime.enable(actor="ops")

    assert isinstance(event, RuntimeEvent)
    assert event.action == ACTION_ENABLE
    assert (event.previous, event.current) == ("stopped", RUNTIME_RUNNING)
    assert runtime.state == RUNTIME_RUNNING
    assert len(runtime.events) == 1

    opened = executor.run(**arguments)

    assert opened.status == AUTO_STATUS_EXECUTED
    assert [intent.qty for intent in backend.intents] == [D("5")]

    disabled = runtime.disable(actor="ops")

    assert disabled is not None
    assert disabled.action == ACTION_DISABLE
    assert runtime.state == RUNTIME_STOPPED
    assert executor.run(**arguments).status == AUTO_STATUS_DISABLED


# ------------------------------------------------------------------ 全局暂停


def test_pause_stops_new_orders_and_keeps_positions(client: TestClient) -> None:
    sync_instruments([make_ref()])
    positions = (account("100"),)
    backend = RecordingBackend()
    runtime = AutoRuntime(clock=ReplayClock(NOW))
    runtime.enable(actor="ops")
    executor = AutoExecutor(
        backend=backend,
        risk=RiskEngine(generous_limits()),
        runtime=runtime,
        positions_provider=lambda: positions,
        clock=ReplayClock(NOW),
    )
    executor.sync_positions()

    runtime.pause(actor="ops")
    arguments = dict(
        instance_id=INSTANCE,
        target=make_target(weight="0.15"),
        instruments={PRODUCT_KEY: spot_ref()},
        prices={SPOT_INST_ID: D("100")},
        capital=D("100000"),
        risk_context=risk_context(),
    )

    paused = executor.run(**arguments)

    assert paused.status == AUTO_STATUS_PAUSED
    assert runtime.state == RUNTIME_PAUSED
    assert backend.intents == []
    assert executor.state.positions == positions

    runtime.resume(actor="ops")
    resumed = executor.run(**arguments)

    assert resumed.status == AUTO_STATUS_EXECUTED
    assert [intent.qty for intent in backend.intents] == [D("50")]
    assert [event.action for event in runtime.events] == [
        ACTION_ENABLE,
        ACTION_PAUSE,
        ACTION_RESUME,
    ]


# ------------------------------------------------------------------ 重复信号抑制


def test_same_target_and_as_of_is_processed_only_once(client: TestClient) -> None:
    sync_instruments([make_ref()])
    backend = RecordingBackend()
    runtime = AutoRuntime(clock=ReplayClock(NOW))
    runtime.enable(actor="ops")
    executor = AutoExecutor(
        backend=backend,
        risk=RiskEngine(generous_limits()),
        runtime=runtime,
        positions_provider=lambda: (),
        clock=ReplayClock(NOW),
    )
    target = make_target(weight="0.5")
    arguments = dict(
        instance_id=INSTANCE,
        target=target,
        instruments={PRODUCT_KEY: spot_ref()},
        prices={SPOT_INST_ID: D("100")},
        capital=D("1000"),
        risk_context=risk_context(),
    )

    first = executor.run(**arguments)
    second = executor.run(**arguments)

    assert first.status == AUTO_STATUS_EXECUTED
    assert first.target_key == target_key(INSTANCE, target)
    assert second.status == AUTO_STATUS_DUPLICATE
    assert second.placements == ()
    assert len(backend.intents) == 1


# ------------------------------------------------------------------ 同步后求差


def test_next_round_uses_synced_venue_positions(client: TestClient) -> None:
    """下单成功但交易所侧仍只有 120 股：下一轮按 120 求差，而不是按本地预期的 150。"""

    sync_instruments([make_ref()])
    current: list[AccountPosition] = [account("100")]
    backend = RecordingBackend()
    runtime = AutoRuntime(clock=ReplayClock(NOW))
    runtime.enable(actor="ops")
    executor = AutoExecutor(
        backend=backend,
        risk=RiskEngine(generous_limits()),
        runtime=runtime,
        positions_provider=lambda: tuple(current),
        clock=ReplayClock(NOW),
    )

    first = executor.run(
        instance_id=INSTANCE,
        target=make_target(weight="0.15", as_of=NOW),
        instruments={PRODUCT_KEY: spot_ref()},
        prices={SPOT_INST_ID: D("100")},
        capital=D("100000"),
        risk_context=risk_context(),
    )
    assert first.status == AUTO_STATUS_EXECUTED
    assert [intent.qty for intent in backend.intents] == [D("50")]

    current[:] = [account("120")]

    second = executor.run(
        instance_id=INSTANCE,
        target=make_target(weight="0.15", as_of=NOW + timedelta(minutes=1)),
        instruments={PRODUCT_KEY: spot_ref()},
        prices={SPOT_INST_ID: D("100")},
        capital=D("100000"),
        risk_context=risk_context(),
    )

    assert second.status == AUTO_STATUS_EXECUTED
    assert [intent.qty for intent in backend.intents] == [D("50"), D("30")]
    assert second.skipped == ()
    assert [position.qty for position in executor.state.positions] == [D("120")]


@pytest.mark.parametrize(
    "target",
    [
        TargetPortfolio(as_of=NOW, legs=()),
        make_target(weight="0"),
    ],
    ids=["product-absent-from-target", "zero-weight-target-leg"],
)
def test_missing_price_when_closing_is_skipped_not_raised(
    target: TargetPortfolio,
) -> None:
    """平仓腿没有价格时只记录跳过，不能让整轮自动执行中断。"""

    backend = RecordingBackend()
    runtime = AutoRuntime(clock=ReplayClock(NOW))
    runtime.enable(actor="ops")
    executor = AutoExecutor(
        backend=backend,
        risk=RiskEngine(generous_limits()),
        runtime=runtime,
        positions_provider=lambda: (account("100"),),
        clock=ReplayClock(NOW),
    )

    result = executor.run(
        instance_id=INSTANCE,
        target=target,
        instruments={PRODUCT_KEY: spot_ref()},
        prices={},
        capital=D("100000"),
        risk_context=risk_context(),
    )

    assert result.status == AUTO_STATUS_EXECUTED
    assert result.intents == ()
    assert result.placements == ()
    assert backend.intents == []
    assert any(
        skip.product_key == PRODUCT_KEY and "没有价格" in skip.reason for skip in result.skipped
    )


# ------------------------------------------------------------------ 假 OKX 端到端


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


def test_fake_okx_end_to_end_reconciles_against_venue_positions(
    client: TestClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    """假 OKX：真实适配器下单成交，下一轮持仓仍按交易所侧实际数量求差。"""

    sync_instruments([make_ref()])
    fake_okx_server.store.book.set_balance("XAAPL", available="100", avg_price="90")
    fake_okx_server.store.book.set_balance("USDT", available="10000")
    fake_okx_server.store.book.set_mark_price(SPOT_INST_ID, "100")

    trade = create_trade_port(settings=_settings(fake_okx_server))

    def venue_positions() -> tuple[AccountPosition, ...]:
        rows = {row.symbol: row for row in list_instruments()}
        return tuple(
            from_venue_position(position, rows[position.inst_id]) for position in trade.positions()
        )

    runtime = AutoRuntime(clock=ReplayClock(NOW))
    runtime.enable(actor="ops")
    executor = AutoExecutor(
        backend=TradePortBackend(trade),
        risk=RiskEngine(generous_limits()),
        runtime=runtime,
        positions_provider=venue_positions,
        clock=ReplayClock(NOW),
    )

    first = executor.run(
        instance_id=INSTANCE,
        target=make_target(weight="0.15", as_of=NOW),
        instruments={PRODUCT_KEY: make_ref()},
        prices={SPOT_INST_ID: D("100")},
        capital=D("100000"),
        risk_context=risk_context(),
    )

    assert first.status == AUTO_STATUS_EXECUTED
    (placement,) = first.placements
    assert placement.order.status == STATUS_FILLED
    assert fake_okx_server.store.book.order_count == 1
    # 假交易所的余额不会因为成交自动变化：交易所侧仍报告 100 股。
    assert [position.qty for position in executor.state.positions] == [D("100")]

    duplicate = executor.run(
        instance_id=INSTANCE,
        target=make_target(weight="0.15", as_of=NOW),
        instruments={PRODUCT_KEY: make_ref()},
        prices={SPOT_INST_ID: D("100")},
        capital=D("100000"),
        risk_context=risk_context(),
    )

    assert duplicate.status == AUTO_STATUS_DUPLICATE
    assert fake_okx_server.store.book.order_count == 1

    later = executor.run(
        instance_id=INSTANCE,
        target=make_target(weight="0.15", as_of=NOW + timedelta(minutes=1)),
        instruments={PRODUCT_KEY: make_ref()},
        prices={SPOT_INST_ID: D("100")},
        capital=D("100000"),
        risk_context=risk_context(),
    )

    assert later.status == AUTO_STATUS_EXECUTED
    assert [placement.order.qty for placement in later.placements] == [D("50")]
    assert fake_okx_server.store.book.order_count == 2

"""回测结果落库与读回：结果表结构、逐腿回放、可复现摘要与错误路径。

用例跑一次真实引擎（两条腿、多空并存、带成本），再落库读回：
- `result_hash` 由可复现输入决定，同参数重跑相同，改动任一输入即变化；
- 给定一次回测能取到每一腿的开平仓、成本与盈亏；
- 指标与逐 bar 曲线在「写入」与「读回」两侧逐字段相同。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import inspect, text

from app.backtest import (
    BacktestInput,
    BacktestRunRecord,
    BacktestSpec,
    CostModel,
    data_fingerprint,
    get_run,
    run_backtest,
    save_run,
)
from app.core import Bar, InstrumentRef, Timeframe, ValidationError
from app.db import init_db, session_scope
from app.strategy import TargetLeg, TargetPortfolio

START = datetime(2026, 3, 2, tzinfo=UTC)
BAR = Timeframe.parse("1h")
TOL = Decimal("1e-9")

#: 两条腿的产品键：A 做多、B 做空，现货形态（乘数为 1），便于手算。
LEG_LONG = "XAAPL-USDT"
LEG_SHORT = "XMSFT-USDT"

#: 滑点 5bp：买入抬高、卖出压低，逐笔手算时直接乘这个系数。
SLIP = Decimal("5") / Decimal("10000")

COSTS = CostModel(
    taker_fee_bps=Decimal("10"),
    maker_fee_bps=Decimal("2"),
    slippage_bps=Decimal("5"),
)


@pytest.fixture()
def backtest_schema() -> None:
    """执行迁移建表；schema 由根 conftest 隔离，用完整块删掉。"""

    init_db()


pytestmark = pytest.mark.usefixtures("backtest_schema")


def moment(index: int) -> datetime:
    return START + timedelta(hours=index)


def candle(inst_id: str, index: int, price: str) -> Bar:
    value = Decimal(price)
    return Bar(
        inst_id=inst_id,
        timeframe=BAR,
        open_time=moment(index),
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal(0),
        confirm=True,
        source="okx",
    )


def instrument(inst_id: str, base: str) -> InstrumentRef:
    return InstrumentRef(
        inst_id=inst_id,
        inst_type="SPOT",
        base_ccy=base,
        quote_ccy="USDT",
        state="live",
        lot_size=Decimal("1"),
        ct_val=None,
    )


def bars() -> dict[str, list[Bar]]:
    """四根小时线：A 从 100 涨到 130，B 始终 50（空腿不赚不亏）。"""

    return {
        LEG_LONG: [
            candle(LEG_LONG, index, price)
            for index, price in enumerate(["100", "110", "120", "130"])
        ],
        LEG_SHORT: [candle(LEG_SHORT, index, "50") for index in range(4)],
    }


def target(index: int, *legs: tuple[str, str, str]) -> TargetPortfolio:
    return TargetPortfolio(
        as_of=moment(index),
        legs=tuple(
            TargetLeg(product_key=key, side=side, target_weight=Decimal(weight))
            for key, side, weight in legs
        ),
    )


def request(*, execution_model: str = "next_open") -> BacktestInput:
    """多空各一条腿：第 0 根建仓、第 2 根给空目标（第 3 根平掉）。"""

    return BacktestInput(
        bars=bars(),
        instruments={
            LEG_LONG: instrument(LEG_LONG, "XAAPL"),
            LEG_SHORT: instrument(LEG_SHORT, "XMSFT"),
        },
        targets=[
            target(0, (LEG_LONG, "long", "0.6"), (LEG_SHORT, "short", "0.2")),
            target(2),
        ],
        initial_capital=Decimal("10000"),
        execution_model=execution_model,
        costs=COSTS,
        settle=None,
    )


def spec(**overrides: object) -> BacktestSpec:
    payload: dict[str, object] = {
        "strategy_instance_id": "si_test",
        "strategy_id": "relative_value",
        "strategy_version": "1.0.0",
        "params": {"fast": 5, "slow": 20},
        "bar": "1h",
        "start_date": date(2026, 3, 2),
        "end_date": date(2026, 3, 3),
        "data_source": "okx",
        "inst_id": LEG_LONG,
        "inst_type": "SPOT",
        "request": {"strategy_instance_id": "si_test", "data_source": "okx"},
        "data_fingerprint": data_fingerprint(bars(), "okx"),
        "execution_model": "next_open",
        "initial_capital": Decimal("10000"),
        "costs": COSTS,
    }
    payload.update(overrides)
    return BacktestSpec(**payload)  # type: ignore[arg-type]


def saved(**overrides: object) -> BacktestRunRecord:
    """跑一次真实引擎并落库，返回读回后的记录（读回即证明持久化无损）。"""

    run_request = request()
    run_spec = spec(**overrides)
    result = run_backtest(run_request)
    record = save_run(run_request, run_spec, result)
    stored = get_run(record.run_id)
    assert stored is not None
    return stored


# ------------------------------------------------------------------ 表结构


def test_result_tables_exist_after_migration() -> None:
    """验收要求的三张表都在库里（等价于 `sqlite3 … ".tables"` 的集合判据）。"""

    with session_scope() as session:
        tables = set(inspect(session.connection()).get_table_names())

    assert {"backtest_runs", "backtest_trades", "backtest_equity"} <= tables


# ------------------------------------------------------------------ 写入与读回


def test_saved_run_keeps_identity_and_summary() -> None:
    record = saved()

    assert record.strategy_instance_id == "si_test"
    assert record.strategy_id == "relative_value"
    assert record.strategy_version == "1.0.0"
    assert record.params == {"fast": 5, "slow": 20}
    assert record.bar == "1h"
    assert (record.start_date, record.end_date) == (date(2026, 3, 2), date(2026, 3, 3))
    assert record.data_source == "okx"
    assert record.execution_model == "next_open"
    assert record.data_fingerprint == spec().data_fingerprint
    assert len(record.result_hash) == 64
    assert record.funding_total == Decimal("0")


def test_metrics_match_the_persisted_curve_and_trades() -> None:
    record = saved()

    assert record.metrics["initial_capital"] == Decimal("10000")
    assert record.metrics["final_capital"] == record.equity[-1].equity
    assert record.metrics["trade_count"] == Decimal(len(record.trades))
    assert record.metrics["max_single_win"] == max(
        (max(item.pnl, Decimal(0)) for item in record.trades), default=Decimal("0")
    )
    assert record.metrics["max_single_loss"] == min(
        (min(item.pnl, Decimal(0)) for item in record.trades), default=Decimal("0")
    )


def test_trades_can_be_replayed_leg_by_leg() -> None:
    """每条腿都能取到开平仓时刻、价格、成本与盈亏；多空两条腿各一笔。"""

    record = saved()

    legs = {item.product_key: item for item in record.trades}
    assert set(legs) == {LEG_LONG, LEG_SHORT}

    long_leg = legs[LEG_LONG]
    assert long_leg.side == "long"
    assert long_leg.inst_type == "SPOT"
    assert long_leg.entry_time == moment(1)
    assert long_leg.exit_time == moment(3)
    # 0.6 × 10000 / 110 向下取整到 1 → 54 份；100 → 130 的价差按含滑点成交价算
    assert long_leg.qty == Decimal("54")
    entry = Decimal("110") * (1 + SLIP)
    exit_ = Decimal("130") * (1 - SLIP)
    assert abs(long_leg.pnl - (exit_ - entry) * 54) < TOL
    assert long_leg.entry_price == entry
    assert long_leg.exit_price == exit_
    assert long_leg.fee > Decimal("0")
    assert long_leg.slippage > Decimal("0")

    short_leg = legs[LEG_SHORT]
    assert short_leg.side == "short"
    # 空腿价格没动，但开仓卖得低、平仓买得贵 → 只亏滑点，成本照记
    assert abs(short_leg.pnl - Decimal("-2")) < TOL
    assert short_leg.fee > Decimal("0")


def test_trade_costs_add_up_to_the_run_costs() -> None:
    """逐腿交易的成本合计必须等于该腿的成交成本合计，不重复也不漏记。"""

    run_request = request()
    result = run_backtest(run_request)
    record = save_run(run_request, spec(), result)

    for cost in result.costs:
        leg_trades = [item for item in record.trades if item.product_key == cost.product_key]
        assert abs(sum((item.fee for item in leg_trades), Decimal(0)) - cost.fee) < TOL
        assert abs(sum((item.slippage for item in leg_trades), Decimal(0)) - cost.slippage) < TOL


def test_equity_curve_and_net_exposure_are_recorded_per_bar() -> None:
    """逐 bar 记录净值与净敞口：目标组合在第 1 根生效，空目标在第 3 根生效。"""

    record = saved()

    assert [point.time for point in record.equity] == [moment(index) for index in range(4)]
    assert [point.time for point in record.exposure] == [point.time for point in record.equity]
    assert [point.net_exposure for point in record.exposure] == [
        Decimal("0"),
        Decimal("0.4"),
        Decimal("0.4"),
        Decimal("0"),
    ]
    assert record.portfolio.net_exposure == Decimal("0")
    assert record.portfolio.leg_win_rate == {LEG_LONG: Decimal("1"), LEG_SHORT: Decimal("0")}
    assert abs(record.portfolio.long_pnl - Decimal("1073.52")) < TOL
    assert abs(record.portfolio.short_pnl - Decimal("-2")) < TOL


def test_unknown_run_returns_none() -> None:
    assert get_run("bt_missing") is None


# ------------------------------------------------------------------ 可复现摘要


def test_same_inputs_produce_the_same_result_hash() -> None:
    first = saved()
    second = saved()

    assert first.run_id != second.run_id
    assert first.result_hash == second.result_hash


@pytest.mark.parametrize(
    ("reason", "overrides"),
    [
        (
            "参数变了",
            {"params": {"fast": 7, "slow": 20}},
        ),
        ("数据区间起点变了", {"start_date": date(2026, 3, 1)}),
        ("数据区间终点变了", {"end_date": date(2026, 3, 4)}),
        ("数据指纹变了", {"data_fingerprint": "0" * 64}),
        ("策略版本变了", {"strategy_version": "1.1.0"}),
        ("数据源变了", {"data_source": "us_equity_proxy"}),
        (
            "成本假设变了",
            {"costs": CostModel(taker_fee_bps=Decimal("4"), slippage_bps=Decimal("1"))},
        ),
    ],
)
def test_result_hash_changes_with_each_reproducibility_input(
    reason: str, overrides: dict[str, object]
) -> None:
    baseline = saved()

    assert saved(**overrides).result_hash != baseline.result_hash, reason


def test_result_hash_changes_with_the_execution_model() -> None:
    baseline = saved()
    alternative_request = request(execution_model="next_close")
    alternative_spec = spec(execution_model="next_close")
    record = save_run(alternative_request, alternative_spec, run_backtest(alternative_request))

    assert record.result_hash != baseline.result_hash


def test_result_hash_ignores_the_run_instance_id() -> None:
    """实例标识不是可复现输入：同一份输入换个实例跑，结果摘要不变。"""

    assert saved().result_hash == saved(strategy_instance_id="si_other").result_hash


# ------------------------------------------------------------------ 行情指纹


def test_data_fingerprint_is_order_independent_and_content_sensitive() -> None:
    forward = data_fingerprint(bars(), "okx")
    reversed_keys = dict(reversed(list(bars().items())))
    assert data_fingerprint(reversed_keys, "okx") == forward

    moved = bars()
    moved[LEG_LONG][3] = candle(LEG_LONG, 3, "131")
    assert data_fingerprint(moved, "okx") != forward
    assert data_fingerprint(bars(), "us_equity_proxy") != forward


def test_data_fingerprint_requires_a_source() -> None:
    with pytest.raises(ValidationError, match="data_source"):
        data_fingerprint(bars(), "  ")


# ------------------------------------------------------------------ 错误路径


@pytest.mark.parametrize(
    ("reason", "overrides"),
    [
        ("实例标识为空", {"strategy_instance_id": ""}),
        ("策略模板为空", {"strategy_id": " "}),
        ("执行模型未知", {"execution_model": "next_bar"}),
        ("周期不在枚举内", {"bar": "2h"}),
        ("区间颠倒", {"start_date": date(2026, 3, 4), "end_date": date(2026, 3, 1)}),
        ("数据源为空", {"data_source": ""}),
        ("数据指纹为空", {"data_fingerprint": ""}),
        ("初始资金不是 Decimal", {"initial_capital": 10000}),
        ("初始资金非正", {"initial_capital": Decimal("0")}),
        ("参数不能序列化", {"params": {"fast": Decimal("5")}}),
    ],
)
def test_spec_rejects_invalid_inputs(reason: str, overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        spec(**overrides)


def test_save_run_rejects_mismatched_execution_model() -> None:
    run_request = request(execution_model="next_close")

    with pytest.raises(ValidationError, match="执行模型不一致"):
        save_run(run_request, spec(), run_backtest(run_request))


def test_save_run_rejects_mismatched_initial_capital() -> None:
    run_request = request()

    with pytest.raises(ValidationError, match="初始资金不一致"):
        save_run(run_request, spec(initial_capital=Decimal("20000")), run_backtest(run_request))


def test_save_run_writes_nothing_when_the_inputs_disagree() -> None:
    """判错之后库里不能留下半条记录：并明确失败发生在一行写入之前。"""

    run_request = request()
    with pytest.raises(ValidationError):
        save_run(run_request, spec(initial_capital=Decimal("20000")), run_backtest(run_request))

    with session_scope() as session:
        rows = session.execute(text("SELECT COUNT(*) FROM backtest_runs")).scalar_one()
    assert rows == 0

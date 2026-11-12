"""回测引擎：组合级 bar 循环、逐腿成交、结算顺序、成本与可复现性。

用例全部手工构造 K 线，不使用随机数：每条断言都对应一个能手算的答案。每个执行模型
各有用例，并断言结果里标注了执行模型标识。
"""

from datetime import UTC, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal

import pytest

from app.backtest import (
    BacktestError,
    BacktestInput,
    BacktestResult,
    BarSeriesError,
    CostModel,
    EquityPoint,
    ExecutionResult,
    LegCost,
    LegExit,
    LegFill,
    LegOrder,
    LegPosition,
    MissingInstrumentError,
    Settlement,
    SettlementOutcome,
    execute_orders,
    execution_price,
    plan_orders,
    resolve_exit,
    run_backtest,
)
from app.core import Bar, InstrumentRef, InvariantViolation, Timeframe, ValidationError
from app.strategy import TargetLeg, TargetPortfolio

START = datetime(2026, 3, 2, tzinfo=UTC)
BAR = Timeframe.parse("1h")

TOL = Decimal("1e-9")
ZERO_COSTS = CostModel()


# ------------------------------------------------------------------ 手工夹具


def moment(index: int) -> datetime:
    return START + timedelta(hours=index)


def candle(
    inst_id: str,
    index: int,
    *,
    open_: str,
    close: str | None = None,
    high: str | None = None,
    low: str | None = None,
) -> Bar:
    """一根已收盘 K 线；未给出的价格按开收价的上下界补齐。"""

    opened = Decimal(open_)
    closed = Decimal(close) if close is not None else opened
    high_ = Decimal(high) if high is not None else max(opened, closed)
    low_ = Decimal(low) if low is not None else min(opened, closed)
    return Bar(
        inst_id=inst_id,
        timeframe=BAR,
        open_time=moment(index),
        open=opened,
        high=high_,
        low=low_,
        close=closed,
        volume=Decimal(0),
        confirm=True,
        source="okx",
    )


def instrument(
    inst_id: str,
    *,
    inst_type: str = "SWAP",
    ct_val: str | None = "1",
    lot_size: str = "1",
) -> InstrumentRef:
    return InstrumentRef(
        inst_id=inst_id,
        inst_type=inst_type,
        base_ccy="BTC",
        quote_ccy="USDT",
        state="live",
        lot_size=Decimal(lot_size),
        ct_val=None if ct_val is None else Decimal(ct_val),
    )


def target(index: int, *legs: tuple[str, str, str]) -> TargetPortfolio:
    return TargetPortfolio(
        as_of=moment(index),
        legs=tuple(
            TargetLeg(product_key=key, side=side, target_weight=Decimal(weight))
            for key, side, weight in legs
        ),
    )


def request(**overrides: object) -> BacktestInput:
    """一份只有一条永续腿的最小输入；各用例按需覆盖字段。"""

    defaults: dict[str, object] = {
        "bars": {"BTC": [candle("BTC-USDT-SWAP", index, open_="100") for index in range(3)]},
        "instruments": {"BTC": instrument("BTC-USDT-SWAP")},
        "targets": [target(0, ("BTC", "long", "0.5"))],
        "initial_capital": Decimal("10000"),
        "execution_model": "next_open",
        "costs": ZERO_COSTS,
        "settle": None,
    }
    defaults.update(overrides)
    return BacktestInput(**defaults)  # type: ignore[arg-type]


# ------------------------------------------------------------------ 执行模型


def test_next_open_fills_at_the_following_bar_open() -> None:
    """`next_open`：目标组合在下一根 K 线的开盘成交。"""

    bars = [
        candle("BTC-USDT-SWAP", 0, open_="100"),
        candle("BTC-USDT-SWAP", 1, open_="120", close="130"),
        candle("BTC-USDT-SWAP", 2, open_="130"),
    ]
    result = run_backtest(request(bars={"BTC": bars}))

    assert result.execution_model == "next_open"
    assert len(result.fills) == 1
    fill = result.fills[0]
    assert fill.bar_open_time == moment(1)
    assert fill.price == Decimal("120")
    assert fill.qty == Decimal("41")  # 0.5 * 10000 / 120 = 41.666…，按 lot_size 1 向下取整
    assert fill.side == "long"
    assert fill.opening is True
    assert result.equity_curve[1] == EquityPoint(
        time=moment(1), equity=Decimal("10410")
    )  # 41 * (130 - 120)


def test_next_close_fills_at_the_following_bar_close() -> None:
    """`next_close`：目标组合在下一根 K 线的收盘成交。"""

    bars = [
        candle("BTC-USDT-SWAP", 0, open_="100"),
        candle("BTC-USDT-SWAP", 1, open_="100", close="110"),
        candle("BTC-USDT-SWAP", 2, open_="110"),
    ]
    result = run_backtest(
        request(
            bars={"BTC": bars},
            initial_capital=Decimal("1000"),
            execution_model="next_close",
        )
    )

    assert result.execution_model == "next_close"
    assert len(result.fills) == 1
    assert result.fills[0].price == Decimal("110")
    assert result.fills[0].qty == Decimal("4")  # 0.5 * 1000 / 110 = 4.54…，取整为 4
    assert result.equity_curve[1].equity == Decimal("1000")


# ------------------------------------------------------------------ 无未来函数


def test_truncating_data_after_a_bar_leaves_earlier_fills_untouched() -> None:
    """把 t 之后的数据整段截断重跑，t 及更早的成交与净值逐字段不变。"""

    prices = ("100", "110", "120", "130")
    bars = [candle("BTC-USDT-SWAP", index, open_=price) for index, price in enumerate(prices)]
    targets = [target(0, ("BTC", "long", "0.5")), target(1, ("BTC", "long", "0.5"))]
    costs = CostModel(taker_fee_bps=Decimal("10"), slippage_bps=Decimal("5"))

    full = run_backtest(request(bars={"BTC": bars}, targets=targets, costs=costs))
    cut = run_backtest(request(bars={"BTC": bars[:2]}, targets=targets, costs=costs))

    cutoff = moment(1)
    assert full.equity_curve[:2] == cut.equity_curve[:2]
    assert [fill for fill in full.fills if fill.bar_open_time <= cutoff] == list(cut.fills)
    assert full.fills != [] and cut.fills != []


# ------------------------------------------------------------------ 多空并存


def test_long_and_short_legs_coexist_and_record_costs_separately() -> None:
    """同一账户同时持有多头与空头腿：两条腿都成交、净敞口是权重之差、成本各记一份。"""

    bars = {
        "AAA": [candle("AAA-USDT-SWAP", index, open_="100") for index in range(3)],
        "BBB": [candle("BBB-USDT-SWAP", index, open_="50") for index in range(3)],
    }
    bars["AAA"][2] = candle("AAA-USDT-SWAP", 2, open_="110")
    bars["BBB"][2] = candle("BBB-USDT-SWAP", 2, open_="45")
    result = run_backtest(
        request(
            bars=bars,
            instruments={"AAA": instrument("AAA-USDT-SWAP"), "BBB": instrument("BBB-USDT-SWAP")},
            targets=[target(0, ("AAA", "long", "0.6"), ("BBB", "short", "0.4"))],
            costs=CostModel(taker_fee_bps=Decimal("5")),
        )
    )

    assert len(result.fills) == 2
    by_key = {fill.product_key: fill for fill in result.fills}
    assert by_key["AAA"].side == "long" and by_key["AAA"].opening is True
    assert by_key["BBB"].side == "short" and by_key["BBB"].opening is True
    assert by_key["AAA"].qty == Decimal("60")  # 0.6 * 10000 / 100
    assert by_key["BBB"].qty == Decimal("80")  # 0.4 * 10000 / 50，空头同样按权重换数量

    costs = {cost.product_key: cost for cost in result.costs}
    assert costs["AAA"].fee == Decimal("3.0")  # 5bp * 60 * 100
    assert costs["BBB"].fee == Decimal("2.0")  # 5bp * 80 * 50
    assert costs["AAA"].fee != costs["BBB"].fee

    assert result.net_exposure == Decimal("0.2")  # 0.6 - 0.4
    assert result.equity_curve[1].equity == Decimal("9995")  # 10000 - 3 - 2
    assert result.equity_curve[2].equity == Decimal("10995")  # 加上两条腿的浮动盈亏 600 + 400


# ------------------------------------------------------------------ 结算顺序


def test_funding_settles_before_the_rebalance_on_the_same_bar() -> None:
    """同一根 bar 上既有资金费又要调仓：资金费先结，调仓数量按结算后的资金换算。

    这根 bar 上资金费扣款 500。顺序正确时可用资金是 9492.4975，目标权重 0.5 换算出的
    数量是 47，持仓从 50 减到 47（减 3）。若先调仓再结算，可用资金是 9992.4975，数量
    是 49（减 1）——两种顺序得到不同结果，本用例把正确的那一个固定下来。
    """

    seen: list[tuple[datetime, Decimal]] = []
    notionals: list[Decimal] = []

    def settle(state: Settlement) -> SettlementOutcome:
        seen.append((state.moment, state.equity))
        for held in state.positions:
            notionals.append(held.notional(state.prices[held.product_key]))
        return SettlementOutcome(cash=Decimal("-500"))

    costs = CostModel(taker_fee_bps=Decimal("10"), slippage_bps=Decimal("5"))
    result = run_backtest(
        request(
            targets=[target(0, ("BTC", "long", "0.5")), target(1, ("BTC", "long", "0.5"))],
            costs=costs,
            settle=settle,
        )
    )

    assert result.funding_total == Decimal("-500")
    # 结算入口看到的是扣款之前的净值；扣款只在它返回之后才落地。
    assert seen == [(moment(2), Decimal("9992.4975"))]
    assert notionals == [Decimal("5000")]  # 50 张 * 100 * 合约面值 1

    reductions = [fill for fill in result.fills if fill.bar_open_time == moment(2)]
    assert len(reductions) == 1
    assert reductions[0].opening is False
    assert reductions[0].qty == Decimal("3")  # 50 - 47

    after_settlement = Decimal("9492.4975")
    reversed_qty = (Decimal("9992.4975") * Decimal("0.5") / Decimal("100")).to_integral_value(
        rounding=ROUND_FLOOR
    )
    expected_qty = (after_settlement * Decimal("0.5") / Decimal("100")).to_integral_value(
        rounding=ROUND_FLOOR
    )
    assert expected_qty == Decimal("47")
    assert reversed_qty == Decimal("49")  # 先调仓会得到这个数量
    assert reductions[0].qty != Decimal("50") - reversed_qty  # 两种顺序结果必须不同


# ------------------------------------------------------------------ 成本手算


def test_cost_matches_the_hand_calculation() -> None:
    """taker 0.1% + 滑点 5bp 的结果与手算值相差小于 1e-9。"""

    costs = CostModel(taker_fee_bps=Decimal("10"), slippage_bps=Decimal("5"))
    result: BacktestResult = run_backtest(
        request(
            instruments={"BTC": instrument("BTC-USDT", inst_type="SPOT", ct_val=None)},
            bars={"BTC": [candle("BTC-USDT", index, open_="100") for index in range(2)]},
            costs=costs,
        )
    )

    fill: LegFill = result.fills[0]
    leg_cost: LegCost = result.costs[0]
    hand_price = Decimal("100") * (Decimal(1) + Decimal("5") / Decimal(10000))
    hand_fee = Decimal("0.001") * Decimal("50") * hand_price
    hand_slippage = Decimal("0.0005") * Decimal("50") * Decimal("100")
    hand_equity = Decimal("10000") - hand_fee - Decimal("50") * (hand_price - Decimal("100"))

    assert fill.qty == Decimal("50")
    assert abs(fill.price - hand_price) < TOL
    assert abs(fill.fee - hand_fee) < TOL
    assert abs(fill.slippage - hand_slippage) < TOL
    assert abs(result.equity_curve[1].equity - hand_equity) < TOL
    assert leg_cost.fee == fill.fee
    assert leg_cost.slippage == fill.slippage


# ------------------------------------------------------------------ 歧义规则


def test_stop_loss_wins_when_both_levels_trigger_on_the_same_bar() -> None:
    """同一 bar 止盈与止损都触发时按止损结算：成交价取止损价。"""

    bars = [candle("BTC-USDT", index, open_="100") for index in range(2)]
    bars.append(candle("BTC-USDT", 2, open_="100", high="110", low="90"))
    result = run_backtest(
        request(
            instruments={"BTC": instrument("BTC-USDT", inst_type="SPOT", ct_val=None)},
            bars={"BTC": bars},
            exits={"BTC": LegExit("BTC", stop_loss=Decimal("95"), take_profit=Decimal("105"))},
        )
    )

    assert len(result.fills) == 2
    exit_fill = result.fills[-1]
    assert exit_fill.reason == "stop_loss"
    assert exit_fill.price == Decimal("95")
    assert exit_fill.opening is False
    assert exit_fill.bar_open_time == moment(2)
    assert result.equity_curve[2].equity == Decimal("9750")  # 10000 + 50 * (95 - 100)


def test_take_profit_settles_when_the_stop_is_not_touched() -> None:
    bars = [candle("BTC-USDT", index, open_="100") for index in range(2)]
    bars.append(candle("BTC-USDT", 2, open_="100", high="110", low="99"))
    result = run_backtest(
        request(
            instruments={"BTC": instrument("BTC-USDT", inst_type="SPOT", ct_val=None)},
            bars={"BTC": bars},
            exits={"BTC": LegExit("BTC", stop_loss=Decimal("95"), take_profit=Decimal("105"))},
        )
    )

    assert result.fills[-1].reason == "take_profit"
    assert result.fills[-1].price == Decimal("105")


@pytest.mark.parametrize("model", ["next_open", "next_close"])
def test_a_stopped_out_leg_is_not_rebuilt_on_the_same_bar(model: str) -> None:
    """同一 bar 既触发止损又有生效目标组合时，止损之后不再按原权重买回。

    不跳过重建时的数字：止损在 95 平掉数量 50（已实现 −250），随后按本 bar 的执行价把
    这条腿又建回来，之后价格继续走到 120，敞口没有下降——净值比「出场后不再重建」
    多出这段浮盈，止损在回测里等于没有生效。
    """

    bars = [candle("BTC-USDT", index, open_="100") for index in range(2)]
    bars.append(candle("BTC-USDT", 2, open_="100", close="105", high="110", low="90"))
    bars.append(candle("BTC-USDT", 3, open_="105", close="120", high="120", low="105"))
    result = run_backtest(
        request(
            instruments={"BTC": instrument("BTC-USDT", inst_type="SPOT", ct_val=None)},
            bars={"BTC": bars},
            targets=[target(0, ("BTC", "long", "0.5")), target(1, ("BTC", "long", "0.5"))],
            execution_model=model,
            exits={"BTC": LegExit("BTC", stop_loss=Decimal("95"), take_profit=Decimal("105"))},
        )
    )

    assert len(result.fills) == 2  # 建仓 + 止损，没有第三次成交
    exit_fill = result.fills[-1]
    assert exit_fill.bar_open_time == moment(2)
    assert exit_fill.reason == "stop_loss"
    assert exit_fill.price == Decimal("95")
    assert exit_fill.opening is False
    # 出场后保持空仓：止损价 95 与 50 的成本差即全部损失，后续涨到 120 不再参与。
    assert result.equity_curve[2].equity == Decimal("9750")
    assert result.equity_curve[3].equity == Decimal("9750")


# ------------------------------------------------------------------ 可复现


def test_same_parameters_produce_the_same_result_hash() -> None:
    costs = CostModel(taker_fee_bps=Decimal("10"), slippage_bps=Decimal("5"))
    first = run_backtest(request(costs=costs))
    second = run_backtest(request(costs=costs))
    changed = run_backtest(request(costs=CostModel(taker_fee_bps=Decimal("10"))))

    assert first.result_hash == second.result_hash
    assert first.result_hash != changed.result_hash  # 参数变了，标识必须跟着变


# ------------------------------------------------------------------ 输入校验


def test_unknown_execution_model_is_rejected() -> None:
    with pytest.raises(ValidationError, match="未知执行模型"):
        run_backtest(request(execution_model="same_bar"))


def test_out_of_order_bars_are_rejected() -> None:
    bars = [
        candle("BTC-USDT-SWAP", 1, open_="100"),
        candle("BTC-USDT-SWAP", 0, open_="100"),
    ]
    with pytest.raises(BarSeriesError, match="严格递增"):
        run_backtest(request(bars={"BTC": bars}))


def test_target_outside_the_bar_timeline_is_rejected() -> None:
    with pytest.raises(ValidationError, match="不在行情时间轴上"):
        run_backtest(request(targets=[target(9, ("BTC", "long", "0.5"))]))


def test_two_targets_on_the_same_bar_are_rejected() -> None:
    with pytest.raises(ValidationError, match="两份目标组合"):
        run_backtest(request(targets=[target(0, ("BTC", "long", "0.5"))] * 2))


def test_missing_instrument_is_rejected() -> None:
    with pytest.raises(MissingInstrumentError, match="没有标的静态信息"):
        run_backtest(request(instruments={}))


def test_backtest_errors_are_input_errors() -> None:
    """域内错误挂在 `ValidationError` 之下：API 边界据此报 400，不必单独分支。"""

    assert issubclass(BarSeriesError, BacktestError)
    assert issubclass(MissingInstrumentError, BacktestError)
    assert issubclass(BacktestError, ValidationError)


# ------------------------------------------------------- 撮合与调仓（纯函数）


def position(
    product_key: str = "BTC",
    *,
    side: str = "long",
    qty: str = "10",
    entry: str = "100",
    multiplier: str = "1",
) -> LegPosition:
    return LegPosition(
        product_key=product_key,
        side=side,
        qty=Decimal(qty),
        entry_price=Decimal(entry),
        entry_time=START,
        multiplier=Decimal(multiplier),
    )


def test_plan_orders_flips_direction_in_two_orders() -> None:
    """方向反转拆成「先平后开」两条订单，不会有一条订单跨过零仓位。"""

    orders = plan_orders(
        target(0, ("BTC", "short", "0.5")),
        {"BTC": position()},
        {"BTC": instrument("BTC-USDT-SWAP")},
        {"BTC": Decimal("100")},
        Decimal("10000"),
    )

    assert len(orders) == 2
    close, open_ = orders
    assert close.opening is False and close.side == "long" and close.qty == Decimal("10")
    assert close.trade_side == "sell"
    assert open_.opening is True and open_.side == "short" and open_.qty == Decimal("50")
    assert open_.trade_side == "sell"


def test_plan_orders_closes_positions_missing_from_the_target() -> None:
    orders = plan_orders(
        TargetPortfolio(as_of=moment(0), legs=()),
        {"BTC": position()},
        {"BTC": instrument("BTC-USDT-SWAP")},
        {"BTC": Decimal("100")},
        Decimal("10000"),
    )

    assert len(orders) == 1
    assert orders[0].reason == "close"
    assert orders[0].qty == Decimal("10")


def test_execute_orders_blends_the_entry_price_when_increasing() -> None:
    outcome: ExecutionResult = execute_orders(
        plan_orders(
            target(0, ("BTC", "long", "1")),
            {"BTC": position(qty="10", entry="100")},
            {"BTC": instrument("BTC-USDT-SWAP")},
            {"BTC": Decimal("200")},
            Decimal("4000"),
        ),
        {"BTC": position(qty="10", entry="100")},
        prices={"BTC": Decimal("200")},
        costs=ZERO_COSTS,
        bar_open_time=moment(1),
    )

    updated = outcome.positions["BTC"]
    assert updated.qty == Decimal("20")
    assert updated.entry_price == Decimal("150")  # (100 * 10 + 200 * 10) / 20


def test_execute_orders_rejects_a_reduction_larger_than_the_position() -> None:
    orders = plan_orders(
        TargetPortfolio(as_of=moment(0), legs=()),
        {"BTC": position(qty="10")},
        {"BTC": instrument("BTC-USDT-SWAP")},
        {"BTC": Decimal("100")},
        Decimal("10000"),
    )
    oversized = LegOrder(
        product_key=orders[0].product_key,
        inst_id=orders[0].inst_id,
        side=orders[0].side,
        qty=Decimal("11"),
        opening=False,
        multiplier=Decimal("1"),
    )

    with pytest.raises(InvariantViolation, match="超过持仓"):
        execute_orders(
            (oversized,),
            {"BTC": position(qty="10")},
            prices={"BTC": Decimal("100")},
            costs=ZERO_COSTS,
            bar_open_time=moment(1),
        )


def test_execution_price_moves_against_the_trader() -> None:
    assert execution_price("buy", Decimal("100"), Decimal("5")) == Decimal("100.05")
    assert execution_price("sell", Decimal("100"), Decimal("5")) == Decimal("99.95")
    with pytest.raises(ValueError, match="unknown trade side"):
        execution_price("hold", Decimal("100"), Decimal("5"))


def test_resolve_exit_mirrors_the_short_side() -> None:
    short = position(side="short", qty="10", entry="100")
    levels = LegExit("BTC", stop_loss=Decimal("110"), take_profit=Decimal("90"))

    assert resolve_exit(short, levels, high=Decimal("111"), low=Decimal("95")) == (
        "stop_loss",
        Decimal("110"),
    )
    assert resolve_exit(short, levels, high=Decimal("105"), low=Decimal("89")) == (
        "take_profit",
        Decimal("90"),
    )
    assert resolve_exit(short, levels, high=Decimal("105"), low=Decimal("95")) is None


def test_settle_hook_is_only_called_while_positions_are_open() -> None:
    """结算入口是注入点：空仓不调用，建仓后的每根 bar 调用一次。"""

    calls: list[datetime] = []

    def settle(state: Settlement) -> SettlementOutcome:
        calls.append(state.moment)
        return SettlementOutcome()

    run_backtest(request(settle=settle))

    assert calls == [moment(2)]

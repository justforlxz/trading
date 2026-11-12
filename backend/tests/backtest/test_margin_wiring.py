"""保证金、杠杆与强平在主循环里真的生效：端到端用例。

T4.5 交付的 `margin_terms` / `margin_used` / `liquidated_in_bar` / `max_loss` 当时没有任何
生产调用方，结算入口只能回传现金。本文件把「接线」这件事固定成断言：用人工摆出来的
档位表与 K 线构造一段会让永续腿强平的行情，断言那条腿在预期的那根 bar 退出、结果里读得到
保证金占用与强平记录——不用「公式算出来等于 X」代替。

每个数字都是手算的答案：

- 档位表：规模 0–1_000_000 张，`maxLever=20`、`mmr=0.005`；本地杠杆上限取 2；
- 开仓：权益 10000、权重 0.5、开仓价 100 → 50 张，名义金额 5000；
- 强平价：`100 × (1/2 − 0.005) = 49.5`，多仓 `100 − 49.5 = 50.5`；
- 保证金占用：`5000 / 2 = 2500`；
- 强平成交：`(50.5 − 100) × 50 = −2475`，权益 `10000 − 2475 = 7525`。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtest import (
    AccountSettlement,
    BacktestInput,
    CostModel,
    FundingSettlement,
    LegLiquidation,
    MarginPoint,
    PositionTier,
    run_backtest,
)
from app.core import Bar, InstrumentRef, Timeframe, ValidationError
from app.market import FundingPoint, parse_funding_rows
from app.strategy import TargetLeg, TargetPortfolio

START = datetime(2026, 3, 2, tzinfo=UTC)  # UTC 零点：资金费结算网格的锚点
HOUR = Timeframe.parse("1h")
FOUR_HOURS = Timeframe.parse("4h")
PRODUCT = "AAPL"
SWAP_ID = "AAPL-USDT-SWAP"
SPOT_ID = "XAAPL-USDT"

#: 一条覆盖全部用例规模的档位：杠杆上限 20、维持保证金率 0.5%。
TIERS = (
    PositionTier(
        size_min=Decimal(0),
        size_max=Decimal(1_000_000),
        max_leverage=Decimal(20),
        maintenance_margin_rate=Decimal("0.005"),
    ),
)

#: 两档表：规模 50 张以内可用 20 倍，超过就掉到 5 倍档（用来证明档位真的被读）。
TIERED = (
    PositionTier(
        size_min=Decimal(0),
        size_max=Decimal(50),
        max_leverage=Decimal(20),
        maintenance_margin_rate=Decimal("0.005"),
    ),
    PositionTier(
        size_min=Decimal(50),
        size_max=Decimal(1_000_000),
        max_leverage=Decimal(5),
        maintenance_margin_rate=Decimal("0.01"),
    ),
)


# ------------------------------------------------------------------ 手工夹具


def at(hours: int) -> datetime:
    return START + timedelta(hours=hours)


def instrument(inst_type: str = "SWAP") -> InstrumentRef:
    if inst_type == "SPOT":
        return InstrumentRef(
            inst_id=SPOT_ID,
            inst_type="SPOT",
            base_ccy="AAPL",
            quote_ccy="USDT",
            state="live",
            lot_size=Decimal("1"),
        )
    return InstrumentRef(
        inst_id=SWAP_ID,
        inst_type="SWAP",
        base_ccy="AAPL",
        quote_ccy="USDT",
        state="live",
        lot_size=Decimal("1"),
        ct_val=Decimal("1"),
    )


def candle(
    index: int,
    *,
    open_: str,
    close: str | None = None,
    high: str | None = None,
    low: str | None = None,
    inst_id: str = SWAP_ID,
    timeframe: Timeframe = HOUR,
) -> Bar:
    """一根已收盘 K 线；未给出的价格按开收价的上下界补齐。"""

    opened = Decimal(open_)
    closed = Decimal(close) if close is not None else opened
    return Bar(
        inst_id=inst_id,
        timeframe=timeframe,
        open_time=at(index),
        open=opened,
        high=Decimal(high) if high is not None else max(opened, closed),
        low=Decimal(low) if low is not None else min(opened, closed),
        close=closed,
        volume=Decimal(0),
        confirm=True,
        source="okx",
    )


def target(hours: int, *, weight: str = "0.5", side: str = "long") -> TargetPortfolio:
    return TargetPortfolio(
        as_of=at(hours),
        legs=(TargetLeg(product_key=PRODUCT, side=side, target_weight=Decimal(weight)),),
    )


def request(
    *,
    bars: Sequence[Bar],
    settle: AccountSettlement,
    targets: Sequence[TargetPortfolio],
    instrument_ref: InstrumentRef,
) -> BacktestInput:
    return BacktestInput(
        bars={PRODUCT: list(bars)},
        instruments={PRODUCT: instrument_ref},
        targets=list(targets),
        initial_capital=Decimal("10000"),
        execution_model="next_open",
        costs=CostModel(),
        settle=settle,
    )


def swap_account(
    *,
    tiers: Sequence[PositionTier] = TIERS,
    funding: FundingSettlement | None = None,
    max_leverage: str = "2",
) -> AccountSettlement:
    return AccountSettlement(
        instruments={PRODUCT: instrument()},
        tiers={PRODUCT: tiers},
        funding=funding,
        max_leverage=Decimal(max_leverage),
    )


def points(
    entries: Sequence[tuple[datetime, str | None, str | None]],
) -> list[FundingPoint]:
    """上游形状的费率行 → 费率点；空串是「上游没给」，`"0"` 是「费率确实为 0」。"""

    rows = [
        {
            "instId": SWAP_ID,
            "fundingTime": str(int(moment.timestamp() * 1000)),
            "fundingRate": "" if funding_rate is None else funding_rate,
            "realizedRate": "" if realized_rate is None else realized_rate,
        }
        for moment, funding_rate, realized_rate in entries
    ]
    return parse_funding_rows(rows, SWAP_ID)


# ------------------------------------------------------- 强平真的让腿退出（永续）


def liquidation_bars(*, inst_id: str = SWAP_ID) -> list[Bar]:
    """第 1 根开盘建仓，第 3 根最低价 40 穿过强平价 50.5。"""

    return [
        candle(0, open_="100", inst_id=inst_id),
        candle(1, open_="100", close="100", inst_id=inst_id),
        candle(2, open_="100", close="100", high="100", low="100", inst_id=inst_id),
        candle(3, open_="100", close="45", high="100", low="40", inst_id=inst_id),
        candle(4, open_="45", close="45", inst_id=inst_id),
    ]


def test_a_swap_leg_is_liquidated_on_the_bar_that_crosses_its_price() -> None:
    """强平价 50.5：第 3 根 bar 最低价 40 穿过它，这条腿就在第 3 根按 50.5 平掉。

    权益按强平价结算（7525），不按收盘价 45（那样是 7250）：两者差 275，正好是
    `(50.5 − 45) × 50`。平掉之后不再按目标组合重建，第 4 根 bar 仍是空仓。
    """

    account = swap_account()
    result = run_backtest(
        request(
            bars=liquidation_bars(),
            settle=account,
            targets=[target(0)],
            instrument_ref=instrument(),
        )
    )

    assert [fill.reason for fill in result.fills] == ["rebalance", "liquidation"]
    open_fill, liquidation_fill = result.fills
    assert open_fill.bar_open_time == at(1)
    assert open_fill.price == Decimal("100")
    assert open_fill.qty == Decimal("50")  # 0.5 * 10000 / 100
    assert liquidation_fill.bar_open_time == at(3)
    assert liquidation_fill.price == Decimal("50.5")
    assert liquidation_fill.qty == Decimal("50")
    assert liquidation_fill.opening is False

    assert result.liquidations == (
        LegLiquidation(
            product_key=PRODUCT, side="long", price=Decimal("50.5"), bar_open_time=at(3)
        ),
    )

    equities = [point.equity for point in result.equity_curve]
    assert equities == [
        Decimal("10000"),
        Decimal("10000"),
        Decimal("10000"),
        Decimal("7525"),
        Decimal("7525"),
    ]
    closed_at_close_price = Decimal("10000") + (Decimal("45") - Decimal("100")) * Decimal("50")
    assert closed_at_close_price == Decimal("7250")
    assert result.equity_curve[3].equity != closed_at_close_price


def test_margin_is_occupied_per_bar_and_equals_equity_minus_available() -> None:
    """保证金占用 2500 出现在「结算时还持着仓」的那两根 bar 上。

    占用的口径是结算步：第 1 根 bar 在结算之后才建仓，占用落在第 2 根；第 3 根在结算时
    仍持着仓（随后才被强平），因此仍有占用；第 4 根空仓，占用回到 0。
    任何一根 bar 上「已占用保证金 + 可用资金 == 权益」都成立。
    """

    result = run_backtest(
        request(
            bars=liquidation_bars(),
            settle=swap_account(),
            targets=[target(0)],
            instrument_ref=instrument(),
        )
    )

    assert isinstance(result.margin_curve[2], MarginPoint)
    assert [point.margin_used for point in result.margin_curve] == [
        Decimal("0"),
        Decimal("0"),
        Decimal("2500"),  # 5000 名义金额 / 杠杆 2
        Decimal("2500"),
        Decimal("0"),
    ]
    assert len(result.margin_curve) == len(result.equity_curve)
    for point, equity in zip(result.margin_curve, result.equity_curve, strict=True):
        assert point.time == equity.time
        assert point.margin_used + point.available == point.equity == equity.equity


def test_margin_used_follows_the_size_and_the_tier() -> None:
    """同一段行情，仓位越大占用越多，且档位一换杠杆就跟着换。

    - 权重的 0.1：10 张 → 落在第一档，杠杆 min(10, 20, 10) = 10 → 占用 1000 / 10 = 100；
    - 权重的 1.0：100 张 → 落在第二档，杠杆 min(10, 5, 10) = 5 → 占用 10000 / 5 = 2000。

    两笔的名义金额相差 10 倍，占用却相差 20 倍：多出来的那一倍来自档位把杠杆砍半。
    """

    bars = [candle(index, open_="100") for index in range(3)]
    small = run_backtest(
        request(
            bars=bars,
            settle=swap_account(tiers=TIERED, max_leverage="10"),
            targets=[target(0, weight="0.1")],
            instrument_ref=instrument(),
        )
    )
    large = run_backtest(
        request(
            bars=bars,
            settle=swap_account(tiers=TIERED, max_leverage="10"),
            targets=[target(0, weight="1.0")],
            instrument_ref=instrument(),
        )
    )

    assert small.fills[0].qty == Decimal("10")
    assert large.fills[0].qty == Decimal("100")
    assert small.margin_curve[2].margin_used == Decimal("100")
    assert large.margin_curve[2].margin_used == Decimal("2000")
    assert small.margin_curve[1].margin_used == Decimal("0")  # 建仓那根还没结算过
    assert large.liquidations == () and small.liquidations == ()


# ------------------------------------------------- 现货：没有永续语义、不会被强平


def test_the_same_market_never_liquidates_a_spot_leg() -> None:
    """同一段行情下的现货腿：不占保证金、没有强平价、不会被强平，一直持有到末日。

    权益按收盘价计价（7250），与永续的 7525 不同——两者的差别正是「永续按强平价结算」。
    """

    result = run_backtest(
        request(
            bars=liquidation_bars(inst_id=SPOT_ID),
            settle=AccountSettlement(instruments={PRODUCT: instrument("SPOT")}, tiers={}),
            targets=[target(0)],
            instrument_ref=instrument("SPOT"),
        )
    )

    assert [fill.reason for fill in result.fills] == ["rebalance"]
    assert result.liquidations == ()
    assert [point.margin_used for point in result.margin_curve] == [Decimal("0")] * 5
    assert [point.equity for point in result.equity_curve] == [
        Decimal("10000"),
        Decimal("10000"),
        Decimal("10000"),
        Decimal("7250"),
        Decimal("7250"),
    ]


# ------------------------------------------------------------ 资金费覆盖率随结果返回


def funding_bars() -> list[Bar]:
    """每 4 小时一根、价格恒为 100：第 `index` 根的开盘时刻是 `index × 4h`。"""

    return [
        candle(index * 4, open_="100", timeframe=FOUR_HOURS)
        for index in range(6)  # 00:00 → 20:00
    ]


def funding_request(funding: FundingSettlement) -> BacktestInput:
    """04:00 建仓 50 张，08:00 与 16:00 各有一个结算点。"""

    return request(
        bars=funding_bars(),
        settle=swap_account(funding=funding, max_leverage="3"),
        targets=[target(0)],
        instrument_ref=instrument(),
    )


def test_the_result_carries_the_funding_coverage_and_the_three_counters() -> None:
    """08:00 有费率、16:00 整条缺失：覆盖率 50%，缺口计数器各记一笔。"""

    funding = FundingSettlement(
        instruments={PRODUCT: instrument()},
        rates={SWAP_ID: points([(at(8), "0.0001", None)])},
    )
    result = run_backtest(funding_request(funding))

    assert result.funding_total == Decimal("-0.5")  # 5000 × 0.0001，只有 08:00 那一笔
    report = result.funding_report
    assert report is not None
    assert (report.expected_points, report.missing_points) == (2, 1)
    assert (report.funding_missing, report.rate_zero) == (0, 0)
    assert report.coverage_pct == Decimal("50.00")


def test_a_missing_rate_is_not_reported_as_a_zero_rate() -> None:
    """「上游费率全缺失」与「费率确实是 0」的 `funding_total` 都是 0，结果层必须分得开。"""

    zero_rates = FundingSettlement(
        instruments={PRODUCT: instrument()},
        rates={SWAP_ID: points([(at(8), "0", None), (at(16), "0", None)])},
    )
    no_rows = FundingSettlement(instruments={PRODUCT: instrument()}, rates={})

    zero = run_backtest(funding_request(zero_rates))
    missing = run_backtest(funding_request(no_rows))

    assert zero.funding_total == missing.funding_total == Decimal("0")
    assert zero.funding_report is not None and missing.funding_report is not None
    assert zero.funding_report.rate_zero == 2
    assert zero.funding_report.missing_points == 0
    assert zero.funding_report.coverage_pct == Decimal("100.00")
    assert missing.funding_report.missing_points == 2
    assert missing.funding_report.rate_zero == 0
    assert missing.funding_report.coverage_pct == Decimal("0.00")


# --------------------------------------------------------------- 复用不再静默


def later_funding_request(funding: FundingSettlement) -> BacktestInput:
    """同一段 4 小时行情整体后移 24 小时：28:00 建仓，32:00 与 40:00 各有一个结算点。"""

    shift = 24
    return request(
        bars=[
            candle(index * 4 + shift, open_="100", timeframe=FOUR_HOURS)
            for index in range(6)  # 24:00 → 44:00
        ],
        settle=swap_account(funding=funding, max_leverage="3"),
        targets=[target(shift)],
        instrument_ref=instrument(),
    )


def test_reusing_one_settlement_on_a_later_window_equals_a_fresh_instance() -> None:
    """同一结算实例跑第二次回测，且第二次时间窗整体更晚：结果与新实例逐字段相同。

    两次回测在 08:00 / 16:00 与 32:00 / 40:00 各结两个点。没有显式的开始边界时，账本
    会把两次回测的 `total` 与计数器累计成 −2.0 / 4 个点；`run_backtest` 在开始时重置
    账本后，第二次的覆盖率只描述它自己，结果与新建实例一致。
    """

    rates = {
        SWAP_ID: points(
            [
                (at(8), "0.0001", None),
                (at(16), "0.0001", None),
                (at(32), "0.0001", None),
                (at(40), "0.0001", None),
            ]
        )
    }
    reused = FundingSettlement(instruments={PRODUCT: instrument()}, rates=rates)
    first = run_backtest(funding_request(reused))
    second = run_backtest(later_funding_request(reused))
    fresh = run_backtest(
        later_funding_request(FundingSettlement(instruments={PRODUCT: instrument()}, rates=rates))
    )

    assert first.funding_report is not None and second.funding_report is not None
    assert first.funding_report.expected_points == 2
    assert second.funding_report.expected_points == 2
    assert second.funding_report.total == Decimal("-1.0")
    assert second.funding_report == fresh.funding_report
    assert second.equity_curve == fresh.equity_curve
    assert second.result_hash == fresh.result_hash


def test_reusing_one_settlement_on_the_same_window_equals_the_first_run() -> None:
    """同一结算实例把同一段回测再跑一次：显式边界让第二次等于第一次，而不是累计成两倍。"""

    shared = FundingSettlement(
        instruments={PRODUCT: instrument()},
        rates={SWAP_ID: points([(at(8), "0.0001", None), (at(16), "0.0002", None)])},
    )
    first = run_backtest(funding_request(shared))
    second = run_backtest(funding_request(shared))

    assert second.funding_report == first.funding_report
    assert second.funding_report is not None
    assert second.funding_report.expected_points == 2
    assert second.funding_total == first.funding_total
    assert second.result_hash == first.result_hash
    assert second.equity_curve == first.equity_curve


# ------------------------------------------------------- 缺档位表不许静默按 0 处理


def test_a_margin_leg_without_a_tier_table_is_rejected() -> None:
    """永续腿没有档位表时直接报错：静默记成 0 占用会让结果看起来「杠杆无限大」。"""

    account = AccountSettlement(instruments={PRODUCT: instrument()}, tiers={})

    with pytest.raises(ValidationError, match="没有杠杆档位表"):
        run_backtest(
            request(
                bars=liquidation_bars(),
                settle=account,
                targets=[target(0)],
                instrument_ref=instrument(),
            )
        )

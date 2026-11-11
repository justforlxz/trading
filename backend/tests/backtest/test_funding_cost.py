"""资金费结算：8 小时结算点、真 0 与缺失的区分、覆盖率计数器，以及两类端到端用例。

费率点由 T4.6 交付的 `parse_funding_rows` 从上游形状的行解析出来（与采集流程同一
条解析路径），费率数值写死在用例里，因此每条断言都对应一个手算答案。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtest import (
    BacktestInput,
    CostModel,
    FundingReport,
    FundingSettlement,
    LegPosition,
    Settlement,
    funding_points_between,
    margin_terms,
    margin_used,
    on_funding_grid,
    run_backtest,
)
from app.core import Bar, InstrumentRef, Timeframe, ValidationError
from app.instrument import TradingRules
from app.instrument import rules as rules_module
from app.instrument.model import SWAP
from app.market import FundingPoint, parse_funding_rows
from app.strategy import TargetLeg, TargetPortfolio

INST_ID = "AAPL-USDT-SWAP"
SPOT_ID = "XAAPL-USDT"
START = datetime(2026, 3, 2, tzinfo=UTC)  # UTC 零点，落在 8 小时结算网格上
BAR = Timeframe.parse("4h")


def at(hours: int) -> datetime:
    """相对 UTC 零点的第 `hours` 小时。"""

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
        inst_id=INST_ID,
        inst_type="SWAP",
        base_ccy="AAPL",
        quote_ccy="USDT",
        state="live",
        lot_size=Decimal("1"),
        ct_val=Decimal("1"),
    )


def points(
    entries: Sequence[tuple[datetime, str | None, str | None]],
) -> list[FundingPoint]:
    """上游形状的费率行 → 费率点；空串是「上游没给」，`"0"` 是「费率确实为 0」。"""

    rows = [
        {
            "instId": INST_ID,
            "fundingTime": str(int(moment.timestamp() * 1000)),
            "fundingRate": "" if funding_rate is None else funding_rate,
            "realizedRate": "" if realized_rate is None else realized_rate,
        }
        for moment, funding_rate, realized_rate in entries
    ]
    return parse_funding_rows(rows, INST_ID)


def position(
    *,
    side: str = "long",
    qty: str = "50",
    entry_price: str = "100",
    entry_time: datetime | None = None,
    multiplier: str = "1",
) -> LegPosition:
    return LegPosition(
        product_key="AAPL",
        side=side,
        qty=Decimal(qty),
        entry_price=Decimal(entry_price),
        entry_time=entry_time or at(0),
        multiplier=Decimal(multiplier),
    )


def state(
    moment: datetime,
    *,
    positions: Sequence[LegPosition] | None = None,
    price: str = "100",
) -> Settlement:
    held = tuple(positions) if positions is not None else (position(),)
    prices = {"AAPL": Decimal(price)} if held else {}
    return Settlement(
        moment=moment,
        equity=Decimal("10000"),
        positions=held,
        prices=prices,
    )


def settlement(entries: Sequence[tuple[datetime, str | None, str | None]], **kwargs: object):
    defaults: dict[str, object] = {
        "instruments": {"AAPL": instrument()},
        "rates": {INST_ID: points(entries)},
    }
    defaults.update(kwargs)
    return FundingSettlement(**defaults)  # type: ignore[arg-type]


# ------------------------------------------------------------------ 结算网格


def test_only_the_eight_hour_grid_is_a_settlement_point() -> None:
    assert on_funding_grid(at(0), 8)
    assert on_funding_grid(at(8), 8)
    assert on_funding_grid(at(16), 8)
    assert not on_funding_grid(at(12), 8)
    assert not on_funding_grid(START.replace(hour=0, minute=30), 8)


def test_points_between_is_half_open_and_steps_by_the_interval() -> None:
    assert funding_points_between(at(0), at(24), 8) == (at(8), at(16), at(24))
    assert funding_points_between(at(8), at(8), 8) == ()
    assert funding_points_between(at(16), at(8), 8) == ()


# ------------------------------------------------------------------ 单点计费


def test_long_pays_a_positive_rate_and_short_receives_it() -> None:
    """名义金额 50 × 100 = 5000，费率 0.0001 → 多头 −0.5、空头 +0.5。"""

    long_book = settlement([(at(8), "0.0001", None)])
    short_book = settlement([(at(8), "0.0001", None)])

    assert long_book(state(at(8))) == Decimal("-0.5")
    assert short_book(state(at(8), positions=[position(side="short")])) == Decimal("0.5")


def test_realized_rate_wins_and_funding_rate_is_the_fallback() -> None:
    """两档费率都在时用 `realizedRate`；只给 `fundingRate` 时才回退。"""

    preferred = settlement([(at(8), "0.0001", "0.0002")])
    fallback = settlement([(at(8), "0.0001", None)])

    assert preferred(state(at(8))) == Decimal("-1")
    assert fallback(state(at(8))) == Decimal("-0.5")


def test_a_zero_rate_is_a_real_sample() -> None:
    """`fundingRate = "0"` 是有效样本：现金流为 0，但不算缺失。"""

    book = settlement([(at(8), "0", None)])

    assert book(state(at(8))) == Decimal(0)
    report = book.report()
    assert report.expected_points == 1
    assert report.covered_points == 1
    assert report.missing_points == 0
    assert report.funding_missing == 0
    assert report.rate_zero == 1
    assert report.coverage_pct == Decimal("100.00")


def test_disabled_funding_charges_nothing() -> None:
    book = settlement([(at(8), "0.0001", None)], enabled=False)

    assert book(state(at(8))) == Decimal(0)
    assert book.report().expected_points == 0
    assert book.report().coverage_pct is None


# ------------------------------------------------------------------ 三个计数器


def test_baseline_counts_every_point_as_covered() -> None:
    book = settlement([(at(8), "0.0001", None), (at(16), "0.0002", None)])

    assert book(state(at(16))) == Decimal("-1.5")
    report = book.report()
    assert report.total == Decimal("-1.5")
    assert report.expected_points == 2
    assert (report.missing_points, report.funding_missing, report.rate_zero) == (0, 0, 0)
    assert report.coverage_pct == Decimal("100.00")


def test_a_deleted_point_raises_only_missing_points() -> None:
    """删掉 08:00 那条记录：missing_points +1，另两个计数器不变。"""

    book = settlement([(at(16), "0.0002", None)])

    assert book(state(at(16))) == Decimal("-1")
    report = book.report()
    assert report.expected_points == 2
    assert report.missing_points == 1
    assert report.funding_missing == 0
    assert report.rate_zero == 0
    assert report.coverage_pct == Decimal("50.00")


def test_a_row_without_any_rate_raises_only_funding_missing() -> None:
    """08:00 那条记录两档费率都为空：funding_missing +1，missing_points 不变。"""

    book = settlement([(at(8), None, None), (at(16), "0.0002", None)])

    assert book(state(at(16))) == Decimal("-1")
    report = book.report()
    assert report.expected_points == 2
    assert report.missing_points == 0
    assert report.funding_missing == 1
    assert report.rate_zero == 0
    assert report.coverage_pct == Decimal("50.00")


# ------------------------------------------------------------------ 时间轴与开仓时刻


def test_a_daily_bar_settles_the_three_points_inside_the_day() -> None:
    """1D 的 bar 一次结掉 08:00 / 16:00 / 24:00 三个点，不是只结整点那一个。"""

    book = settlement([(at(8), "0.0001", None), (at(16), "0.0001", None), (at(24), "0.0001", None)])

    assert book(state(at(24))) == Decimal("-1.5")
    assert book.report().expected_points == 3


def test_points_before_the_position_was_opened_are_not_charged() -> None:
    """08:00 才开仓的腿不补扣 00:00 的结算点。"""

    book = settlement([(at(0), "0.0001", None), (at(8), "0.0001", None), (at(16), "0.0001", None)])

    assert book(state(at(16), positions=[position(entry_time=at(8))])) == Decimal("-0.5")
    assert book.report().expected_points == 1


def test_spot_legs_never_reach_the_funding_grid() -> None:
    """现货没有资金费：既不产生现金流，也不进入覆盖率的分母。"""

    book = settlement(
        [(at(8), "0.0001", None)],
        instruments={"AAPL": instrument("SPOT")},
    )

    assert book(state(at(8))) == Decimal(0)
    report = book.report()
    assert report.expected_points == 0
    assert report.total == Decimal(0)


def test_a_position_without_instrument_static_data_is_rejected() -> None:
    book = FundingSettlement(instruments={}, rates={})

    with pytest.raises(ValidationError):
        book(state(at(8)))


# ------------------------------------------------------------------ 端到端


def candle(index: int, inst_id: str) -> Bar:
    """每 4 小时一根、价格恒为 100 的 K 线：第 `index` 根的开盘时刻是 `index × 4h`。"""

    price = Decimal("100")
    return Bar(
        inst_id=inst_id,
        timeframe=BAR,
        open_time=at(index * 4),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal(0),
        confirm=True,
        source="okx",
    )


def target(hours: int, *, side: str = "long", weight: str = "0.5") -> TargetPortfolio:
    return TargetPortfolio(
        as_of=at(hours),
        legs=(TargetLeg(product_key="AAPL", side=side, target_weight=Decimal(weight)),),
    )


def request(*, instrument_ref: InstrumentRef, settle: object) -> BacktestInput:
    return BacktestInput(
        bars={"AAPL": [candle(index, instrument_ref.inst_id) for index in range(7)]},
        instruments={"AAPL": instrument_ref},
        targets=[target(0), target(4), target(8), target(12), target(16)],
        initial_capital=Decimal("10000"),
        execution_model="next_open",
        costs=CostModel(),
        settle=settle,  # type: ignore[arg-type]
    )


def test_swap_backtest_charges_funding_at_each_point() -> None:
    """永续端到端：04:00 建仓 50 张，08:00 / 16:00 / 24:00 各结一次资金费。

    08:00 扣 5000 × 0.0001 = 0.5，净值降到 9999.5，当根调仓按结算后的资金换算成
    49 张；16:00 与 24:00 各扣 4900 × 0.0002 = 0.98。资金费合计 −2.46，收盘净值
    9997.54。
    """

    book = settlement(
        [
            (at(8), "0.0001", None),
            (at(16), "0.0002", None),
            (at(24), "0.0002", None),
        ]
    )
    result = run_backtest(request(instrument_ref=instrument(), settle=book))

    assert result.funding_total == Decimal("-2.46")
    assert result.equity_curve[-1].equity == Decimal("9997.54")
    report: FundingReport = book.report()
    assert report.total == Decimal("-2.46")
    assert report.expected_points == 3
    assert (report.missing_points, report.funding_missing, report.rate_zero) == (0, 0, 0)
    assert report.coverage_pct == Decimal("100.00")


def test_spot_backtest_has_no_funding_no_margin_and_no_liquidation() -> None:
    """现货端到端：同一段行情下杠杆 1、保证金 0、无强平价、资金费 0。"""

    book = settlement(
        [
            (at(8), "0.0001", None),
            (at(16), "0.0002", None),
            (at(24), "0.0002", None),
        ],
        instruments={"AAPL": instrument("SPOT")},
    )
    result = run_backtest(request(instrument_ref=instrument("SPOT"), settle=book))

    assert result.funding_total == Decimal(0)
    assert result.equity_curve[-1].equity == Decimal("10000")
    assert book.report().expected_points == 0

    terms = margin_terms(
        inst_type="SPOT", side="long", entry_price=Decimal("100"), size=Decimal(50)
    )
    assert terms.leverage == Decimal(1)
    assert terms.liquidation_price is None
    assert margin_used(terms, Decimal("5000")) == Decimal(0)


def test_settlement_reads_the_category_table_instead_of_hardcoding_perp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """把 SWAP 的规则表换成「无保证金、无资金费」，同一段永续行情立刻按全额买入结算。

    这条用例替代「数 `inst_type` 分支」的文本 grep：结算与保证金口径确实从
    `trading_rules()` 取值，而不是在函数里写死「永续就要收资金费、占保证金」。
    `qty_unit` 保持 `contract`，因此变化的只有 `has_margin` / `has_funding` 两格。
    """

    swapped = TradingRules(
        tick_size_required=True,
        min_order_size_required=True,
        max_leverage=None,
        has_margin=False,
        has_funding=False,
        funding_interval_hours=None,
        session_kind="equity",
        state_kinds=frozenset({"live", "suspend", "preopen"}),
        has_position_endpoint=True,
        qty_unit="contract",
    )
    monkeypatch.setattr(rules_module, "_RULES", {**rules_module._RULES, SWAP: swapped})

    book = settlement(
        [
            (at(8), "0.0001", None),
            (at(16), "0.0002", None),
            (at(24), "0.0002", None),
        ]
    )
    result = run_backtest(request(instrument_ref=instrument(), settle=book))

    assert result.funding_total == Decimal(0)
    assert book.report().expected_points == 0

    terms = margin_terms(
        inst_type="SWAP", side="long", entry_price=Decimal("100"), size=Decimal("50")
    )
    assert terms.has_margin is False
    assert terms.leverage == Decimal(1)
    assert terms.liquidation_price is None
    assert margin_used(terms, Decimal("5000")) == Decimal(0)

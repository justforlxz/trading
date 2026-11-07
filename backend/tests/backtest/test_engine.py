"""回测引擎：无未来数据、成本手算与窗口切分规则（AC4/AC6/AC9）。"""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.backtest.costs import CostModel
from app.backtest.engine import Bar, BarSeries, LegSpec, Window, simulate, validate_windows
from app.backtest.errors import BacktestError
from tests.backtest.support import at

TOL = Decimal("1e-6")
QUANT = Decimal("1e-10")


def series(instrument_id: int, points: list[tuple[int, str]]) -> BarSeries:
    return BarSeries(
        instrument_id=instrument_id,
        bars=tuple(Bar(ts=at(hour=hour), close=Decimal(price)) for hour, price in points),
    )


def leg(weight: str = "1", side: str = "long", instrument_id: int = 1) -> LegSpec:
    return LegSpec(
        instrument_id=instrument_id,
        inst_id=f"SYM{instrument_id}-USDT-SWAP",
        side=side,
        target_weight=Decimal(weight),
    )


def test_bar_series_never_exposes_future_bars() -> None:
    bars = series(1, [(0, "100"), (8, "110"), (16, "120")])
    for hour in (0, 4, 8, 12, 16, 20):
        visible = bars.upto(at(hour=hour))
        assert all(bar.ts <= at(hour=hour) for bar in visible)
        assert max((bar.ts for bar in visible), default=at(hour=hour)) <= at(hour=hour)
        latest = bars.last_at(at(hour=hour))
        assert latest is None or latest.ts <= at(hour=hour)


def test_engine_ignores_bars_outside_the_window() -> None:
    """窗口结束后插入 100 倍极端 bar，结果必须逐位相同。"""

    inside = series(1, [(0, "100"), (8, "110")])
    with_extreme = BarSeries(
        instrument_id=1,
        bars=(*inside.bars, Bar(ts=at(hour=16), close=Decimal("11000"))),
    )
    kwargs = {
        "legs": [leg()],
        "initial_capital": Decimal("100000"),
        "cost_model": CostModel(),
        "window_start": at(hour=0),
        "window_end": at(hour=16),
    }
    baseline = simulate(series={1: inside}, **kwargs)
    perturbed = simulate(series={1: with_extreme}, **kwargs)
    assert baseline == perturbed


def test_costs_match_hand_computation() -> None:
    simulation = simulate(
        legs=[leg()],
        series={1: series(1, [(0, "100"), (8, "110")])},
        initial_capital=Decimal("100000"),
        cost_model=CostModel(
            taker_fee_bps=Decimal("10"),
            slippage_bps=Decimal("5"),
            funding_bps_per_period=Decimal("1"),
        ),
        window_start=at(hour=0),
        window_end=at(hour=12),
    )
    assert len(simulation.trades) == 1
    trade = simulation.trades[0]

    entry_px = Decimal("100") * (Decimal(1) + Decimal("0.0005"))
    exit_px = Decimal("110") * (Decimal(1) - Decimal("0.0005"))
    qty = (Decimal("100000") / entry_px).quantize(QUANT)
    entry_notional = qty * entry_px
    exit_notional = qty * exit_px
    fees = Decimal("10") / Decimal(10000) * (entry_notional + exit_notional)
    funding = Decimal("1") / Decimal(10000) * entry_notional
    slippage = Decimal("5") / Decimal(10000) * (entry_notional + exit_notional)
    gross = qty * (exit_px - entry_px)
    net = gross - fees - funding

    assert trade.entry_px == entry_px.quantize(Decimal("1e-10"))
    assert trade.exit_px == exit_px.quantize(Decimal("1e-10"))
    assert abs(trade.qty - qty) < TOL
    assert abs(trade.fees - fees) < TOL
    assert abs(trade.funding - funding) < TOL
    assert abs(trade.slippage - slippage) < TOL
    assert abs(trade.gross_pnl - gross) < TOL
    assert abs(trade.net_pnl - net) < TOL
    assert trade.bars_held == 2
    assert trade.exit_reason == "window_end"

    final = simulation.equity[-1].equity
    assert abs(final - (Decimal("100000") + net)) < TOL


def test_short_position_pnl_and_funding_sign() -> None:
    simulation = simulate(
        legs=[leg(weight="-1", side="short")],
        series={1: series(1, [(0, "100"), (8, "90")])},
        initial_capital=Decimal("100000"),
        cost_model=CostModel(funding_bps_per_period=Decimal("1")),
        window_start=at(hour=0),
        window_end=at(hour=12),
    )
    trade = simulation.trades[0]
    # 空头价格下跌盈利；资金费为负（收取）。
    assert trade.gross_pnl > 0
    assert trade.funding < 0
    assert trade.net_pnl > trade.gross_pnl


@pytest.mark.parametrize(
    ("exit_hour", "crossings"),
    [(7, 0), (8, 1), (16, 2)],
)
def test_funding_boundary_counting(exit_hour: int, crossings: int) -> None:
    simulation = simulate(
        legs=[leg()],
        series={1: series(1, [(0, "100"), (exit_hour, "100")])},
        initial_capital=Decimal("1000"),
        cost_model=CostModel(funding_bps_per_period=Decimal("1")),
        window_start=at(hour=0),
        window_end=at(hour=20),
    )
    trade = simulation.trades[0]
    expected = Decimal(crossings) * (Decimal("1") / Decimal(10000)) * Decimal("1000")
    assert abs(trade.funding - expected) < TOL


def test_two_runs_are_bit_identical() -> None:
    kwargs = {
        "legs": [leg("0.5", "long", 1), leg("-0.5", "short", 2)],
        "series": {
            1: series(1, [(0, "100"), (8, "103"), (16, "99")]),
            2: series(2, [(0, "50"), (8, "49"), (16, "52")]),
        },
        "initial_capital": Decimal("50000"),
        "cost_model": CostModel(taker_fee_bps=Decimal("3"), slippage_bps=Decimal("2")),
        "window_start": at(hour=0),
        "window_end": at(hour=20),
    }
    assert simulate(**kwargs) == simulate(**kwargs)


def test_window_validation_rejects_overlap_and_wrong_order() -> None:
    first = Window(name="train", start=at(day=1), end=at(day=5), role="train")
    second = Window(name="test", start=at(day=6), end=at(day=10), role="test")
    validate_windows([first, second])  # 不抛错

    overlapping = Window(name="test", start=at(day=4), end=at(day=10), role="test")
    with pytest.raises(BacktestError) as overlap:
        validate_windows([first, overlapping])
    assert overlap.value.code == "backtest_window_overlap"

    wrong_order = Window(name="train2", start=at(day=11), end=at(day=12), role="train")
    with pytest.raises(BacktestError) as order:
        validate_windows([first, second, wrong_order])
    assert order.value.code == "backtest_walk_forward_order"

    with pytest.raises(BacktestError) as invalid:
        validate_windows([Window(name="empty", start=at(day=2), end=at(day=2))])
    assert invalid.value.code == "backtest_window_invalid"


def test_train_window_ends_before_test_window_starts() -> None:
    train = Window(name="train", start=at(day=1), end=at(day=5), role="train")
    test = Window(name="test", start=at(day=6), end=at(day=10), role="test")
    assert train.end < test.start
    assert train.end + timedelta(0) <= test.start

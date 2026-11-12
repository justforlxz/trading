"""回测指标：13 个标的级指标、逐腿完整交易、净敞口序列与四项组合级指标。

用例全部手算：每个指标给出一个能手算的期望值，零交易与空曲线给出约定值。逐腿配对用
「加权平均成本」口径，与引擎的持仓记账一致，因此成交手续费的合计必然等于成本表中该腿的
合计——这条对账断言就写在本文件里。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtest.metrics import (
    METRIC_NAMES,
    ClosedTrade,
    ExposurePoint,
    closed_trades,
    compute_metrics,
    default_annualization_factor,
    exposure_series,
    portfolio_metrics,
)
from app.backtest.simulation import LegFill
from app.core import InstrumentRef, InvariantViolation, ValidationError
from app.strategy import TargetLeg, TargetPortfolio

TOL = Decimal("1e-9")
START = datetime(2026, 3, 2, tzinfo=UTC)


def moment(hours: int) -> datetime:
    return START + timedelta(hours=hours)


def trade(
    product_key: str,
    side: str,
    pnl: str,
    *,
    hours: int,
    inst_id: str | None = None,
) -> ClosedTrade:
    """一条已配对完成的交易；开平仓价格按盈亏反推，只看盈亏与持仓时长。"""

    pnl_value = Decimal(pnl)
    entry_price = Decimal("100")
    exit_price = entry_price + pnl_value
    return ClosedTrade(
        product_key=product_key,
        inst_id=inst_id or f"{product_key}-USDT",
        inst_type="SPOT",
        side=side,
        qty=Decimal("1"),
        entry_price=entry_price,
        entry_time=moment(0),
        exit_price=exit_price,
        exit_time=moment(hours),
        fee=Decimal("0"),
        slippage=Decimal("0"),
        pnl=pnl_value,
        reason="close",
    )


def fill(
    product_key: str,
    side: str,
    qty: str,
    price: str,
    hour: int,
    *,
    opening: bool,
    fee: str,
    slippage: str,
) -> LegFill:
    return LegFill(
        product_key=product_key,
        inst_id=f"{product_key}-USDT-SWAP",
        side=side,
        qty=Decimal(qty),
        price=Decimal(price),
        bar_open_time=moment(hour),
        fee=Decimal(fee),
        slippage=Decimal(slippage),
        opening=opening,
        reason="rebalance" if opening else "close",
    )


def instrument(product_key: str, *, ct_val: str = "10") -> InstrumentRef:
    return InstrumentRef(
        inst_id=f"{product_key}-USDT-SWAP",
        inst_type="SWAP",
        base_ccy=product_key,
        quote_ccy="USDT",
        state="live",
        lot_size=Decimal("1"),
        ct_val=Decimal(ct_val),
    )


def metrics(**overrides: object) -> dict[str, Decimal]:
    payload: dict[str, object] = {
        "equity": [Decimal("1000"), Decimal("1100"), Decimal("1050"), Decimal("1200")],
        "initial_capital": Decimal("1000"),
        "trades": [
            trade("BTC", "long", "20", hours=2),
            trade("ETH", "short", "5", hours=1),
            trade("BTC", "long", "-10", hours=3),
        ],
        "annualization_factor": Decimal("3"),
        "risk_free_rate": Decimal("0"),
    }
    payload.update(overrides)
    return compute_metrics(**payload)  # type: ignore[arg-type]


# ------------------------------------------------------------------ 标的级指标


def test_metric_names_cover_the_prd_list() -> None:
    """13 个标量指标（清单第 14 项资金曲线是序列，不在键集合里）。"""

    assert len(METRIC_NAMES) == 13
    assert set(metrics()) == set(METRIC_NAMES)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # 初始资金原样回显，最终资金取曲线最后一个点。
        ("initial_capital", Decimal("1000")),
        ("final_capital", Decimal("1200")),
        # (1200 - 1000) / 1000 = 0.2
        ("total_return", Decimal("0.2")),
        # 3 个周期、年化因子 3 → (1.2)^(3/3) - 1 = 0.2
        ("annualized_return", Decimal("0.2")),
        # 峰值 1100 → 回撤到 1050，幅度 50 / 1100
        ("max_drawdown", Decimal("50") / Decimal("1100")),
        # 3 笔交易里 2 笔盈利
        ("win_rate", Decimal("2") / Decimal("3")),
        # 平均盈利 (20 + 5) / 2 = 12.5，平均亏损 10 → 1.25
        ("profit_loss_ratio", Decimal("1.25")),
        # 盈利之和 25 / 亏损之和 10 = 2.5
        ("profit_factor", Decimal("2.5")),
        ("trade_count", Decimal("3")),
        # 持仓 2h + 1h + 3h，均值 2h
        ("average_holding_hours", Decimal("2")),
        ("max_single_win", Decimal("20")),
        ("max_single_loss", Decimal("-10")),
    ],
)
def test_every_metric_matches_hand_computation(name: str, expected: Decimal) -> None:
    assert abs(metrics()[name] - expected) < TOL


def test_sharpe_matches_hand_computation() -> None:
    """三个周期收益率的均值除总体标准差，再乘年化因子的平方根。"""

    equity = [Decimal("1000"), Decimal("1100"), Decimal("1050"), Decimal("1200")]
    returns = [
        Decimal("0.1"),
        (Decimal("1050") - Decimal("1100")) / Decimal("1100"),
        (Decimal("1200") - Decimal("1050")) / Decimal("1050"),
    ]
    mean = sum(returns, Decimal(0)) / Decimal(3)
    std = (sum(((value - mean) ** 2 for value in returns), Decimal(0)) / Decimal(3)).sqrt()

    assert abs(metrics(equity=equity)["sharpe"] - mean / std * Decimal(3).sqrt()) < TOL


def test_annualization_factor_and_risk_free_rate_are_used() -> None:
    baseline = metrics()
    faster = metrics(annualization_factor=Decimal("252"))
    assert faster["annualized_return"] != baseline["annualized_return"]
    assert faster["sharpe"] != baseline["sharpe"]

    with_rate = metrics(risk_free_rate=Decimal("0.03"))
    assert with_rate["sharpe"] < baseline["sharpe"]


def test_zero_trades_returns_agreed_values_without_raising() -> None:
    """零交易：盈亏类指标一律 0，胜率不除零，持仓时长不除零。"""

    flat = metrics(equity=[Decimal("1000"), Decimal("1000")], trades=[])

    assert flat["final_capital"] == Decimal("1000")
    assert flat["total_return"] == Decimal("0")
    assert flat["annualized_return"] == Decimal("0")
    assert flat["max_drawdown"] == Decimal("0")
    assert flat["sharpe"] == Decimal("0")
    assert flat["win_rate"] == Decimal("0")
    assert flat["profit_loss_ratio"] == Decimal("0")
    assert flat["profit_factor"] == Decimal("0")
    assert flat["trade_count"] == Decimal("0")
    assert flat["average_holding_hours"] == Decimal("0")
    assert flat["max_single_win"] == Decimal("0")
    assert flat["max_single_loss"] == Decimal("0")


def test_empty_equity_curve_falls_back_to_initial_capital() -> None:
    empty = metrics(equity=[], trades=[])

    assert empty["final_capital"] == Decimal("1000")
    assert empty["total_return"] == Decimal("0")
    assert empty["max_drawdown"] == Decimal("0")


def test_negative_capital_is_never_annualized_into_nonsense() -> None:
    """亏光（增长因子 ≤ 0）时年化收益记 -100%，不抛对数定义域错误。"""

    wiped = metrics(equity=[Decimal("1000"), Decimal("0")], trades=[])

    assert wiped["annualized_return"] == Decimal("-1")


def test_default_annualization_factor() -> None:
    assert default_annualization_factor("1d") == Decimal("252")
    assert default_annualization_factor("1h") == Decimal("8760")
    assert default_annualization_factor("4h") == Decimal("2190")


# ------------------------------------------------------------------ 逐腿完整交易


def open_then_close_fills() -> tuple[LegFill, ...]:
    """先两次加仓、再两次平仓（一次部分、一次全部），数字都能手算。"""

    return (
        fill("BTC", "long", "2", "100", 0, opening=True, fee="1", slippage="0.5"),
        fill("BTC", "long", "1", "110", 1, opening=True, fee="0.5", slippage="0.25"),
        fill("BTC", "long", "1", "120", 2, opening=False, fee="2", slippage="1"),
        fill("BTC", "long", "2", "90", 3, opening=False, fee="4", slippage="2"),
    )


def test_closed_trades_pair_by_weighted_average_cost() -> None:
    """加权开仓价 (100×2 + 110×1)/3，乘数取合约面值 10。"""

    opened = closed_trades(open_then_close_fills(), {"BTC": instrument("BTC")})

    assert len(opened) == 2
    blended = (Decimal("100") * 2 + Decimal("110")) / Decimal("3")
    first, second = opened

    assert first.entry_price == blended
    assert first.entry_time == moment(0)
    assert first.exit_price == Decimal("120")
    assert first.exit_time == moment(2)
    # (120 - 103.333…) × 1 × 10
    assert abs(first.pnl - (Decimal("120") - blended) * 10) < TOL
    # 开仓手续费 1.5 按 1/3 分摊 + 本次平仓手续费 2
    assert abs(first.fee - (Decimal("2") + Decimal("1.5") / 3)) < TOL
    assert abs(first.slippage - (Decimal("1") + Decimal("0.75") / 3)) < TOL
    assert first.inst_type == "SWAP"
    assert first.inst_id == "BTC-USDT-SWAP"

    # (90 - 103.333…) × 2 × 10，剩下的开仓成本全部计入这一笔
    assert abs(second.pnl - (Decimal("90") - blended) * 2 * 10) < TOL
    assert abs(second.fee - (Decimal("4") + Decimal("1.5") * 2 / 3)) < TOL
    assert second.exit_time == moment(3)


def test_closed_trade_pnl_and_cost_totals_match_the_fills() -> None:
    """配对不改变总额：盈亏之和与成交成本之和都必须逐位对上。"""

    fills = open_then_close_fills()
    opened = closed_trades(fills, {"BTC": instrument("BTC")})

    realized = sum((item.pnl for item in opened), Decimal(0))
    blended = (Decimal("100") * 2 + Decimal("110")) / Decimal("3")
    assert abs(realized - ((Decimal("120") - blended) + (Decimal("90") - blended) * 2) * 10) < TOL
    assert sum((item.fee for item in opened), Decimal(0)) == sum(
        (item.fee for item in fills), Decimal(0)
    )
    assert sum((item.slippage for item in opened), Decimal(0)) == sum(
        (item.slippage for item in fills), Decimal(0)
    )


def test_closed_trades_restart_after_a_full_close() -> None:
    """平干净之后再开仓，开仓时刻与均价都从头算，不带上上一笔的成本。"""

    fills = (
        fill("BTC", "long", "1", "100", 0, opening=True, fee="1", slippage="0"),
        fill("BTC", "long", "1", "110", 1, opening=False, fee="1", slippage="0"),
        fill("BTC", "long", "1", "200", 5, opening=True, fee="1", slippage="0"),
        fill("BTC", "long", "1", "230", 6, opening=False, fee="1", slippage="0"),
    )

    opened = closed_trades(fills, {"BTC": instrument("BTC")})

    assert [item.entry_time for item in opened] == [moment(0), moment(5)]
    assert [item.entry_price for item in opened] == [Decimal("100"), Decimal("200")]
    assert abs(opened[1].pnl - Decimal("300")) < TOL


@pytest.mark.parametrize(
    ("reason", "fills", "error"),
    [
        (
            "平仓找不到同方向持仓",
            (fill("BTC", "long", "1", "100", 0, opening=False, fee="0", slippage="0"),),
            InvariantViolation,
        ),
        (
            "平仓数量超过持仓",
            (
                fill("BTC", "long", "1", "100", 0, opening=True, fee="0", slippage="0"),
                fill("BTC", "long", "2", "110", 1, opening=False, fee="0", slippage="0"),
            ),
            InvariantViolation,
        ),
        (
            "建仓成交跨过零仓位",
            (
                fill("BTC", "long", "1", "100", 0, opening=True, fee="0", slippage="0"),
                fill("BTC", "short", "1", "110", 1, opening=True, fee="0", slippage="0"),
            ),
            InvariantViolation,
        ),
    ],
)
def test_closed_trades_reject_inconsistent_fills(
    reason: str, fills: tuple[LegFill, ...], error: type[Exception]
) -> None:
    with pytest.raises(error):
        closed_trades(fills, {"BTC": instrument("BTC")})


def test_closed_trades_require_instrument_static_info() -> None:
    """没有标的静态信息就换不出名义金额，直接报错而不是按乘数 1 硬算。"""

    from app.backtest import MissingInstrumentError

    with pytest.raises(MissingInstrumentError):
        closed_trades(
            (fill("BTC", "long", "1", "100", 0, opening=True, fee="0", slippage="0"),), {}
        )


# ------------------------------------------------------------------ 组合级指标


def target(hour: int, *legs: tuple[str, str, str]) -> TargetPortfolio:
    return TargetPortfolio(
        as_of=moment(hour),
        legs=tuple(
            TargetLeg(product_key=key, side=side, target_weight=Decimal(weight))
            for key, side, weight in legs
        ),
    )


def test_exposure_series_follows_the_one_bar_lag() -> None:
    """目标组合在下一根 bar 生效：t0 的目标在 t1 收盘时才算在用。"""

    targets = [
        target(
            0,
            ("A", "long", "0.4"),
            ("B", "long", "0.3"),
            ("C", "short", "0.1"),
            ("D", "short", "0.1"),
        ),
        target(2, ("A", "long", "0.2")),
    ]
    points = exposure_series(targets, [moment(0), moment(1), moment(2), moment(3)])

    assert [point.net_exposure for point in points] == [
        Decimal("0"),
        Decimal("0.5"),
        Decimal("0.5"),
        Decimal("0.2"),
    ]


def test_exposure_series_rejects_two_targets_at_the_same_moment() -> None:
    with pytest.raises(ValidationError, match="同一时刻"):
        exposure_series(
            [target(0, ("A", "long", "0.5")), target(0, ("A", "long", "0.2"))],
            [moment(0), moment(1)],
        )


def test_exposure_series_rejects_targets_off_the_timeline() -> None:
    """轴外的目标永远不会生效，不能静默把它记成净敞口 0。"""

    with pytest.raises(ValidationError, match="不在行情时间轴上"):
        exposure_series([target(1, ("A", "long", "0.5"))], [moment(0), moment(2)])


def test_portfolio_metrics_match_hand_computation_for_two_long_two_short_legs() -> None:
    """多空各两腿：净敞口、每腿胜率、多腿合计盈亏、空腿合计盈亏逐项手算。"""

    trades = (
        trade("A", "long", "30", hours=1),
        trade("A", "long", "-10", hours=2),
        trade("B", "long", "20", hours=3),
        trade("C", "short", "15", hours=4),
        trade("D", "short", "-25", hours=5),
        trade("D", "short", "5", hours=6),
    )
    targets = [
        target(
            0,
            ("A", "long", "0.4"),
            ("B", "long", "0.3"),
            ("C", "short", "0.1"),
            ("D", "short", "0.1"),
        )
    ]
    exposure = exposure_series(targets, [moment(0), moment(1)])

    portfolio = portfolio_metrics(trades, exposure)

    # 多头权重 0.4 + 0.3 = 0.7，空头权重 0.1 + 0.1 = 0.2 → 净敞口 0.5
    assert abs(portfolio.net_exposure - Decimal("0.5")) < TOL
    # 逐腿胜率：A 1/2、B 1/1、C 1/1、D 1/2
    assert portfolio.leg_win_rate == {
        "A": Decimal("0.5"),
        "B": Decimal("1"),
        "C": Decimal("1"),
        "D": Decimal("0.5"),
    }
    # 多腿 30 - 10 + 20 = 40；空腿 15 - 25 + 5 = -5
    assert abs(portfolio.long_pnl - Decimal("40")) < TOL
    assert abs(portfolio.short_pnl - Decimal("-5")) < TOL


def test_portfolio_metrics_without_trades_or_exposure() -> None:
    portfolio = portfolio_metrics((), ())

    assert portfolio.net_exposure == Decimal("0")
    assert portfolio.long_pnl == Decimal("0")
    assert portfolio.short_pnl == Decimal("0")
    assert portfolio.leg_win_rate == {}


def test_exposure_point_carries_its_bar_time() -> None:
    point = ExposurePoint(time=moment(0), net_exposure=Decimal("0.5"))

    assert point.time == moment(0)

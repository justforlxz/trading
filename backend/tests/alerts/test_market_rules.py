"""大盘异动与组合异动的纯函数判定。

三个指数的日常波动差三倍，因此阈值一律是 ATR 的倍数：固定百分比在费半上六十个交易日
会响 29 次（见 `test_sox_replay_stays_below_the_noise_floor` 的对照），等于没有提醒。

这里的用例都不碰数据库：输入是日线与收益率读数，断言只看「跨过哪一档」「去重键是否
按方向与级别稳定」。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.alerts.rules import (
    MARKET_ATR_PERIOD,
    SCAN_MANAGED_RULES,
    SPREAD_RULE_ID,
    US10Y_RULE_ID,
    WATCHLIST_RULE_ID,
    atr_pct,
    market_index_candidates,
    market_rule_id,
    spread_candidates,
    us10y_candidates,
    watchlist_candidates,
)
from app.core import Bar, Timeframe
from app.market import MARKET_INDEXES

START = datetime(2026, 8, 3, 13, 30, tzinfo=UTC)
MOMENT = datetime(2026, 11, 24, 21, 30, tzinfo=UTC)
NDX, GSPC, SOX = MARKET_INDEXES
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "market"


def _bar(
    index: int,
    close: str,
    *,
    range_pct: str | None = None,
    symbol: str = "^NDX",
    confirm: bool = True,
) -> Bar:
    """一根日线；`range_pct` 给定时把高低点摆成收盘价的固定百分比波幅。"""

    value = Decimal(close)
    half = value * Decimal(range_pct or "0.0282") / 2
    return Bar(
        inst_id=symbol,
        timeframe=Timeframe.parse("1d"),
        open_time=START + timedelta(days=index),
        open=value,
        high=value + half,
        low=value - half,
        close=value,
        volume=Decimal("1"),
        confirm=confirm,
        source="yahoo",
    )


def _flat_baseline(count: int = MARKET_ATR_PERIOD + 1) -> list[Bar]:
    """收平、波幅恒为 2.82% 的基线：ATR20 恰好是 2.82%。"""

    return [_bar(index, "100") for index in range(count)]


def _with_move(pct: str) -> list[Bar]:
    baseline = _flat_baseline()
    return [*baseline, _bar(len(baseline), str(Decimal("100") * (1 + Decimal(pct) / 100)))]


def test_atr_pct_uses_wilder_smoothing_on_daily_bars() -> None:
    """已知答案：波幅恒为收盘价的 2.82% 时，ATR20 就是 2.82%。"""

    assert atr_pct(_flat_baseline()) == pytest.approx(Decimal("2.82"), abs=Decimal("0.0001"))


def test_atr_pct_needs_a_previous_close() -> None:
    """只有 period 根时第 0 根没有前收盘，起点会把波动低估，因此不给值。"""

    assert atr_pct(_flat_baseline()[:MARKET_ATR_PERIOD]) is None


def test_atr_pct_ignores_unconfirmed_bars() -> None:
    """未收盘的最后一根不进 ATR：它的价格还会变。"""

    bars = _flat_baseline()
    bars.append(_bar(len(bars), "130", confirm=False))

    assert atr_pct(bars) == pytest.approx(Decimal("2.82"), abs=Decimal("0.0001"))


@pytest.mark.parametrize(
    ("move", "severity"),
    [("4.3", "info"), ("7.1", "warning"), ("11.4", "critical")],
)
def test_index_bands_are_atr_multiples(move: str, severity: str) -> None:
    """AC2：ATR20=2.82% 时，4.3% 提示、7.1% 警告、11.4% 紧急。"""

    found = market_index_candidates(NDX, _with_move(move), moment=MOMENT)

    assert len(found) == 1
    assert found[0].type == "market"
    assert found[0].severity == severity
    assert found[0].instrument_id is None
    assert found[0].rule_id == market_rule_id("ndx")
    assert found[0].dedup_key == f"market|market_ndx_change|^NDX|up|{severity}"
    assert found[0].payload["atr20_pct"] == "2.82"


def test_a_move_below_the_info_band_stays_silent() -> None:
    """没跨过任何一档就不发提醒，也不预热。"""

    assert market_index_candidates(NDX, _with_move("4.0"), moment=MOMENT) == []


def test_direction_is_part_of_the_dedup_key() -> None:
    """同一级别、不同方向是两条提醒：涨 4.3% 与跌 4.3% 说的是两件事。"""

    up = market_index_candidates(NDX, _with_move("4.3"), moment=MOMENT)[0]
    down_bars = [*_flat_baseline(), _bar(MARKET_ATR_PERIOD + 1, "95.7")]
    down = market_index_candidates(NDX, down_bars, moment=MOMENT)[0]

    assert up.dedup_key != down.dedup_key
    assert up.dedup_key.endswith("|up|info")
    assert down.dedup_key.endswith("|down|info")


def test_the_dedup_key_does_not_carry_the_bar_date() -> None:
    """连续三天同一级别必须落在同一个键上，否则每天都会新增一条提醒。

    日期只进载荷（`bar`），不进键：状态跃迁去重靠的是「键相同即同级持续」。
    """

    found = market_index_candidates(NDX, _with_move("4.3"), moment=MOMENT)[0]

    assert found.payload["bar"] == "2026-08-24"
    assert found.payload["bar"] not in found.dedup_key


def test_sox_replay_stays_below_the_noise_floor() -> None:
    """AC3：近 60 个交易日真实费半日线回放，ATR 自适应只发 5 条。

    同一段窗口里「固定 2% 阈值」会响 29 次——费半的日常波动本来就有 6%，固定百分比
    等于没有提醒。两个数字放在一起才是这条规则的意义。
    """

    fixture = json.loads((FIXTURES / "sox_daily.json").read_text(encoding="utf-8"))
    bars = [
        Bar(
            inst_id=fixture["symbol"],
            timeframe=Timeframe.parse(fixture["bar"]),
            open_time=datetime.fromisoformat(row["date"]).replace(tzinfo=UTC),
            open=Decimal(row["open"]),
            high=Decimal(row["high"]),
            low=Decimal(row["low"]),
            close=Decimal(row["close"]),
            volume=Decimal("0"),
            confirm=True,
            source=fixture["source"],
        )
        for row in fixture["bars"]
    ]
    # 前 21 根是 ATR 基线，之后 60 根是回放窗口。
    replay_start = MARKET_ATR_PERIOD + 1
    alerts = 0
    fixed_hits = 0
    for index in range(replay_start, len(bars)):
        found = market_index_candidates(SOX, bars[: index + 1], moment=MOMENT)
        alerts += len(found)
        change = (bars[index].close - bars[index - 1].close) / bars[index - 1].close * 100
        if abs(change) >= 2:
            fixed_hits += 1

    assert len(bars) - replay_start == 60
    assert alerts == 5
    assert alerts <= 8
    assert fixed_hits == 29
    assert alerts * 5 < fixed_hits


@pytest.mark.parametrize(
    ("change_bp", "severity"),
    [("12", "info"), ("22", "warning"), ("32", "critical")],
)
def test_us10y_bands_are_basis_points(change_bp: str, severity: str) -> None:
    """AC4：10Y 单日 +12bp 提示、+22bp 警告、+32bp 紧急。"""

    found = us10y_candidates(
        change_pp=Decimal(change_bp) / 100,
        value=Decimal("4.632"),
        trading_day=datetime(2026, 11, 20, tzinfo=UTC).date(),
        moment=MOMENT,
    )

    assert len(found) == 1
    assert found[0].severity == severity
    assert found[0].rule_id == US10Y_RULE_ID
    assert found[0].dedup_key == f"market|{US10Y_RULE_ID}|us10y|up|{severity}"
    assert found[0].payload["change_bp"] == f"{Decimal(change_bp):.1f}"


def test_us10y_below_ten_basis_points_is_silent() -> None:
    assert (
        us10y_candidates(
            change_pp=Decimal("0.09"),
            value=Decimal("4.5"),
            trading_day=datetime(2026, 11, 20, tzinfo=UTC).date(),
            moment=MOMENT,
        )
        == []
    )


def test_spread_turning_negative_reports_a_new_inversion() -> None:
    """AC4：2Y→10Y 由正转负 → 一条「新形成倒挂」。"""

    found = spread_candidates(
        current_bp=Decimal("-2"),
        previous_bp=Decimal("8"),
        trading_day=datetime(2026, 11, 20, tzinfo=UTC).date(),
        moment=MOMENT,
    )

    assert len(found) == 1
    assert found[0].rule_id == SPREAD_RULE_ID
    assert found[0].severity == "info"
    assert found[0].title == "2Y→10Y 新形成倒挂"
    assert found[0].dedup_key == f"market|{SPREAD_RULE_ID}|2s10s|inverted|info"
    assert found[0].payload["inverted"] is True


def test_spread_unwinding_an_inversion_reports_once() -> None:
    found = spread_candidates(
        current_bp=Decimal("3"),
        previous_bp=Decimal("-1"),
        trading_day=datetime(2026, 11, 20, tzinfo=UTC).date(),
        moment=MOMENT,
    )

    assert [item.title for item in found] == ["2Y→10Y 解除倒挂"]


def test_spread_change_under_ten_basis_points_is_silent() -> None:
    assert (
        spread_candidates(
            current_bp=Decimal("30"),
            previous_bp=Decimal("24"),
            trading_day=datetime(2026, 11, 20, tzinfo=UTC).date(),
            moment=MOMENT,
        )
        == []
    )


def _watchlist_bars(decliners: int) -> dict[str, list[Bar]]:
    """7 个标的、22 个交易日：前 21 天每天 +1%，最后一天 `decliners` 个跌 2%。

    组合 ATR20 取异动日之前的 20 个交易日，因此基线恰好是 1.00%；最后一天 2% 的跌幅
    是 2 倍，跨过 1.5 倍的门槛。
    """

    series: dict[str, list[Bar]] = {}
    for symbol_index in range(7):
        symbol = f"SYM{symbol_index}"
        closes = [Decimal("100") * Decimal("1.01") ** day for day in range(21)]
        factor = Decimal("0.98") if symbol_index < decliners else Decimal("1.01")
        closes.append(closes[-1] * factor)
        series[symbol] = [
            _bar(index, str(close), range_pct="0.02", symbol=symbol)
            for index, close in enumerate(closes)
        ]
    return series


def test_watchlist_reports_one_alert_when_seventy_percent_fall() -> None:
    """AC5：7 个自选里 5 个下跌且平均 -2% → 一条组合异动。"""

    found = watchlist_candidates(_watchlist_bars(decliners=5), moment=MOMENT)

    assert len(found) == 1
    assert found[0].type == "watchlist"
    assert found[0].severity == "info"
    assert found[0].instrument_id is None
    assert found[0].rule_id == WATCHLIST_RULE_ID
    assert found[0].dedup_key == f"watchlist|{WATCHLIST_RULE_ID}|all|down|info"
    assert found[0].payload["decliners"] == 5
    assert found[0].payload["participants"] == 7
    assert found[0].payload["average_decline_pct"] == "2.00"
    assert found[0].payload["portfolio_atr20_pct"] == "1.00"


def test_watchlist_stays_silent_when_fewer_than_seventy_percent_fall() -> None:
    """AC5：只有 4 个下跌（57%）时不发。"""

    assert watchlist_candidates(_watchlist_bars(decliners=4), moment=MOMENT) == []


def test_watchlist_needs_enough_history_for_the_portfolio_atr() -> None:
    """组合 ATR 要 20 个交易日的基线；不够时不猜一个波动率出来。"""

    series = _watchlist_bars(decliners=5)
    short = {symbol: bars[-10:] for symbol, bars in series.items()}

    assert watchlist_candidates(short, moment=MOMENT) == []


def test_every_new_rule_belongs_to_the_scan_managed_set() -> None:
    """新规则的提醒必须由扫描管生命周期，否则永远停在 pending。"""

    assert {market_rule_id(index.key) for index in MARKET_INDEXES} <= SCAN_MANAGED_RULES
    assert {US10Y_RULE_ID, SPREAD_RULE_ID, WATCHLIST_RULE_ID} <= SCAN_MANAGED_RULES

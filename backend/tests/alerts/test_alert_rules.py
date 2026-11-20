"""提醒纯函数：指标穿越、RSI 区间、趋势变化、价格区间、数据缺口与去重键。

这些函数不碰数据库，输入是一串日线与一个时点；断言只看规则是否在正确的 bar
上触发、去重键是否随标的/规则/bar/方向变化，以及未完成 K 线是否被排除。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.alerts.rules import (
    SCAN_MANAGED_RULES,
    data_gap_candidates,
    price_range_candidates,
    technical_candidates,
)
from app.core import Bar, Timeframe
from app.market import CandleGap, IntegrityReport
from app.risk import (
    RULE_HIGH_LEVERAGE,
    RULE_MARGIN_USAGE,
    RULE_SINGLE_INSTRUMENT_WEIGHT,
    RULE_STOP_DISTANCE,
    RULE_STOP_MISSING,
)

START = datetime(2026, 1, 1, tzinfo=UTC)
MOMENT = datetime(2026, 3, 1, tzinfo=UTC)


def _bar(
    index: int, close: str, *, high: str | None = None, low: str | None = None, confirm: bool = True
) -> Bar:
    value = Decimal(close)
    return Bar(
        inst_id="TEST-USDT",
        timeframe=Timeframe.parse("1d"),
        open_time=START + timedelta(days=index),
        open=value,
        high=Decimal(high) if high is not None else value,
        low=Decimal(low) if low is not None else value,
        close=value,
        volume=Decimal("1"),
        confirm=confirm,
        source="okx",
    )


def _bars(closes: list[str], **kwargs: object) -> list[Bar]:
    return [_bar(index, close, **kwargs) for index, close in enumerate(closes)]


def test_ma20_cross_down_uses_latest_confirmed_bar() -> None:
    bars = _bars(["100"] * 20 + ["80"])

    found = [
        item
        for item in technical_candidates("TEST-USDT", bars, moment=MOMENT)
        if item.rule_id == "ma20_cross"
    ]

    assert len(found) == 1
    assert found[0].title == "收盘价跌破 MA20"
    assert found[0].severity == "info"
    assert found[0].triggered_at == MOMENT
    assert found[0].dedup_key == (
        f"indicator|ma20_cross|TEST-USDT|{bars[-1].open_time.isoformat()}|down"
    )


def test_rsi_zone_reports_oversold_entry() -> None:
    bars = _bars(["100", "101"] + ["101"] * 14 + ["96"])

    found = [
        item
        for item in technical_candidates("TEST-USDT", bars, moment=MOMENT)
        if item.rule_id == "rsi_zone"
    ]

    assert len(found) == 1
    assert found[0].title == "RSI 进入超卖观察区"
    assert found[0].payload["threshold"] == "30"
    assert found[0].dedup_key.endswith("|oversold")


def test_trend_change_detects_bearish_to_neutral() -> None:
    bars = _bars(["100"] * 30 + [str(100 - index) for index in range(1, 31)] + ["200"])

    found = [
        item
        for item in technical_candidates("TEST-USDT", bars, moment=MOMENT)
        if item.rule_id == "trend_change"
    ]

    assert len(found) == 1
    assert found[0].payload == {"from": "bearish", "to": "neutral"}
    assert found[0].dedup_key.endswith("|neutral")


def test_unconfirmed_bar_cannot_trigger_confirmed_alert() -> None:
    bars = [*_bars(["100"] * 20), _bar(20, "80", confirm=False)]

    found = [
        item
        for item in technical_candidates("TEST-USDT", bars, moment=MOMENT)
        if item.rule_id == "ma20_cross"
    ]

    assert found == []


def test_price_range_uses_previous_20_bars_excluding_latest() -> None:
    bars = [_bar(index, "95", high="100", low="90") for index in range(20)]
    bars.append(_bar(20, "99.5", high="100.5", low="99"))

    found = price_range_candidates("TEST-USDT", bars, moment=MOMENT)

    assert [item.rule_id for item in found] == ["near_20d_high"]
    assert found[0].payload["high_20d"] == "100"
    assert found[0].payload["distance_pct"] == "0.50"
    assert found[0].dedup_key.startswith("price|near_20d_high|TEST-USDT|")


def test_data_gap_reports_the_first_gap_once_per_start() -> None:
    gap = CandleGap(
        start=datetime(2026, 1, 5, tzinfo=UTC),
        end=datetime(2026, 1, 8, tzinfo=UTC),
        missing=3,
    )
    report = IntegrityReport(
        symbol="TEST-USDT",
        bar="1d",
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 10, tzinfo=UTC),
        expected=10,
        present=7,
        missing=3,
        gaps=(gap,),
        duplicates=(),
    )

    first = data_gap_candidates("TEST-USDT", report, moment=MOMENT)
    second = data_gap_candidates("TEST-USDT", report, moment=MOMENT + timedelta(days=1))

    assert len(first) == 1
    assert first[0].type == "data"
    assert first[0].severity == "warning"
    assert first[0].payload == {
        "missing": 3,
        "start": "2026-01-05T00:00:00+00:00",
        "end": "2026-01-08T00:00:00+00:00",
    }
    assert first[0].dedup_key == second[0].dedup_key


def test_no_candidates_without_a_gap() -> None:
    report = IntegrityReport(
        symbol="TEST-USDT",
        bar="1d",
        start=None,
        end=None,
        expected=0,
        present=0,
        missing=0,
        gaps=(),
        duplicates=(),
    )

    assert data_gap_candidates("TEST-USDT", report, moment=MOMENT) == []


def test_every_scan_candidate_rule_belongs_to_the_scan_managed_set() -> None:
    """扫描产出的每个 `rule_id` 都在归属集合里。

    新增一条扫描规则却忘了写进 `SCAN_MANAGED_RULES` 时，它的提醒会在下一次扫描被
    「过期」处理掉，这条用例就是那道门。
    """

    gap = CandleGap(
        start=datetime(2026, 1, 5, tzinfo=UTC),
        end=datetime(2026, 1, 8, tzinfo=UTC),
        missing=3,
    )
    report = IntegrityReport(
        symbol="TEST-USDT",
        bar="1d",
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 10, tzinfo=UTC),
        expected=10,
        present=7,
        missing=3,
        gaps=(gap,),
        duplicates=(),
    )
    produced: set[str] = set()
    produced.update(
        item.rule_id
        for item in technical_candidates("TEST-USDT", _bars(["100"] * 20 + ["80"]), moment=MOMENT)
    )
    produced.update(
        item.rule_id
        for item in technical_candidates(
            "TEST-USDT", _bars(["100", "101"] + ["101"] * 14 + ["96"]), moment=MOMENT
        )
    )
    produced.update(
        item.rule_id
        for item in technical_candidates(
            "TEST-USDT",
            _bars(["100"] * 30 + [str(100 - index) for index in range(1, 31)] + ["200"]),
            moment=MOMENT,
        )
    )
    range_bars = [_bar(index, "95", high="100", low="90") for index in range(20)]
    range_bars.append(_bar(20, "99.5", high="100.5", low="99"))
    produced.update(
        item.rule_id for item in price_range_candidates("TEST-USDT", range_bars, moment=MOMENT)
    )
    low_bars = [_bar(index, "95", high="110", low="90") for index in range(20)]
    low_bars.append(_bar(20, "90.5", high="91", low="90"))
    produced.update(
        item.rule_id for item in price_range_candidates("TEST-USDT", low_bars, moment=MOMENT)
    )
    produced.update(
        item.rule_id for item in data_gap_candidates("TEST-USDT", report, moment=MOMENT)
    )

    # 三条技术规则、两条价格区间规则、一条数据规则都要真的被这次构造产出。
    assert produced == {
        "ma20_cross",
        "rsi_zone",
        "trend_change",
        "near_20d_high",
        "near_20d_low",
        "candle_gap",
    }
    assert produced <= SCAN_MANAGED_RULES


def test_scan_managed_set_covers_every_risk_rule_constant() -> None:
    """风险规则用常量登记，改了常量名也不会让集合与规则脱节。"""

    assert {
        RULE_STOP_MISSING,
        RULE_STOP_DISTANCE,
        RULE_HIGH_LEVERAGE,
        RULE_SINGLE_INSTRUMENT_WEIGHT,
        RULE_MARGIN_USAGE,
    } <= SCAN_MANAGED_RULES

"""自选行日线聚合：趋势、RSI、ATR 与数据覆盖的已知答案。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core import Bar, Timeframe
from app.watchlist.metrics import summarize_daily

DAY = timedelta(days=1)
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _bars(closes: list[str], *, half_range: str = "0.5") -> list[Bar]:
    """按收盘序列造日线；每根都带固定高低差，ATR 才有非零真值。"""

    spread = Decimal(half_range)
    rows: list[Bar] = []
    for index, raw in enumerate(closes):
        close = Decimal(raw)
        rows.append(
            Bar(
                inst_id="XAAPL-USDT",
                timeframe=Timeframe.parse("1d"),
                open_time=BASE + DAY * index,
                open=close,
                high=close + spread,
                low=close - spread,
                close=close,
                volume=Decimal("10"),
                confirm=True,
                source="okx",
            )
        )
    return rows


def test_empty_history_is_missing_not_zero() -> None:
    snapshot = summarize_daily([])

    assert snapshot.candle_count == 0
    assert snapshot.data_status == "missing"
    assert snapshot.last_price is None
    assert snapshot.change_pct_24h is None
    assert snapshot.volume_24h_quote is None
    assert snapshot.last_candle_at is None
    assert snapshot.trend is None
    assert snapshot.rsi_14 is None
    assert snapshot.atr_pct_14 is None


def test_single_bar_has_price_but_no_change_or_indicators() -> None:
    snapshot = summarize_daily(_bars(["100"]))

    assert snapshot.candle_count == 1
    assert snapshot.data_status == "partial"
    assert snapshot.last_price == Decimal("100")
    assert snapshot.change_pct_24h is None
    assert snapshot.trend is None
    assert snapshot.rsi_14 is None
    assert snapshot.atr_pct_14 is None


def test_twenty_bars_are_partial_because_trend_needs_sixty() -> None:
    closes = [str(100 + index) for index in range(20)]
    snapshot = summarize_daily(_bars(closes))

    assert snapshot.candle_count == 20
    assert snapshot.data_status == "partial"
    assert snapshot.trend is None
    assert snapshot.rsi_14 == Decimal("100.00")
    assert snapshot.atr_pct_14 is not None


def test_rising_sixty_bars_are_bullish_with_full_coverage() -> None:
    closes = [str(100 + index) for index in range(60)]
    snapshot = summarize_daily(_bars(closes))

    assert snapshot.candle_count == 60
    assert snapshot.data_status == "ok"
    assert snapshot.last_price == Decimal("159")
    assert snapshot.change_pct_24h == Decimal("0.632911")
    assert snapshot.trend == "bullish"
    assert snapshot.rsi_14 == Decimal("100.00")
    # 收盘逐日上涨 1、高低各差 0.5，真实波幅稳定在 1.5；ATR/close = 1.5/159。
    assert snapshot.atr_pct_14 == Decimal("0.94")
    assert snapshot.last_candle_at == BASE + DAY * 59


def test_falling_sixty_bars_are_bearish() -> None:
    closes = [str(100 + (59 - index)) for index in range(60)]
    snapshot = summarize_daily(_bars(closes))

    assert snapshot.trend == "bearish"
    assert snapshot.rsi_14 == Decimal("0.000000")


def test_flat_sixty_bars_are_neutral() -> None:
    snapshot = summarize_daily(_bars(["100"] * 60))

    assert snapshot.trend == "neutral"
    assert snapshot.rsi_14 is None


def test_previous_close_zero_keeps_change_empty() -> None:
    snapshot = summarize_daily(_bars(["0", "100"]))

    assert snapshot.last_price == Decimal("100")
    assert snapshot.change_pct_24h is None
    assert snapshot.volume_24h_quote is None
    assert snapshot.data_status == "partial"

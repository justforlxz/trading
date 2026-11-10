"""读侧编排：可用区间、缺口/重复报告、两标的按 open_time 对齐的相关性。

所有期望值都由「同步了哪些窗口」反推；完整性报告只报事实，不补齐任何数据。
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select

from app.core import Bar, Timeframe, ValidationError
from app.db import session_scope
from app.market import (
    Candle,
    correlation,
    data_range,
    expected_open_times,
    integrity,
    sync_candles,
    upsert_candles,
)

SYMBOL_A = "XAAPL-USDT"
SYMBOL_B = "XMSFT-USDT"
ASSET_TYPE = "tokenized_equity"
WINDOW_END = datetime(2026, 11, 6, 16, 0, tzinfo=UTC)


def _bar(
    open_time: datetime,
    *,
    symbol: str = SYMBOL_A,
    bar: str = "1h",
    source: str = "okx",
) -> Bar:
    return Bar(
        inst_id=symbol,
        timeframe=Timeframe.parse(bar),
        open_time=open_time,
        open=Decimal("10.00"),
        high=Decimal("11.00"),
        low=Decimal("9.00"),
        close=Decimal("10.50"),
        volume=Decimal("100.00"),
        confirm=True,
        source=source,
    )


def _sync_window(port, symbol: str, hours: int, *, end: datetime = WINDOW_END) -> datetime:
    start = end - timedelta(hours=hours)
    sync_candles(
        port, symbol, "1h", start, end, inst_type="SPOT", asset_type=ASSET_TYPE, source="okx_spot"
    )
    return start


def _delete_bars(symbol: str, open_times: list[datetime]) -> None:
    with session_scope() as session:
        session.execute(
            delete(Candle).where(
                Candle.symbol == symbol,
                Candle.bar == "1h",
                Candle.open_time.in_([int(open_time.timestamp()) for open_time in open_times]),
            )
        )


def _row_count(symbol: str) -> int:
    with session_scope() as session:
        return session.scalar(
            select(func.count()).select_from(Candle).where(Candle.symbol == symbol)
        )


# ------------------------------------------------------------------- 可用区间


def test_data_range_reports_the_real_first_and_last_bar(market_port) -> None:
    start = _sync_window(market_port, SYMBOL_A, 5)

    # 不补齐、不外推：最后一根就是 END - 1 个周期。
    assert data_range(SYMBOL_A, "1h") == (start, WINDOW_END - timedelta(hours=1))


def test_data_range_is_none_when_nothing_was_stored() -> None:
    assert data_range(SYMBOL_A, "1h") is None


# --------------------------------------------------------------------- 缺口


def test_integrity_counts_every_missing_bar(market_port) -> None:
    start = _sync_window(market_port, SYMBOL_A, 10)
    absent = [start + timedelta(hours=offset) for offset in (2, 5, 8)]
    _delete_bars(SYMBOL_A, absent)
    assert _row_count(SYMBOL_A) == 7

    report = integrity(SYMBOL_A, "1h")

    assert report.expected == 10
    assert report.present == 7
    assert report.missing == 3
    assert len(report.gaps) == 3
    assert [gap.missing for gap in report.gaps] == [1, 1, 1]
    assert [gap.start for gap in report.gaps] == absent
    assert report.duplicates == ()
    assert report.start == start
    assert report.end == WINDOW_END - timedelta(hours=1)
    # 报告只读：查完行数不变，没有任何补造。
    assert _row_count(SYMBOL_A) == 7


def test_integrity_merges_contiguous_missing_bars_into_one_gap(market_port) -> None:
    start = _sync_window(market_port, SYMBOL_A, 10)
    _delete_bars(SYMBOL_A, [start + timedelta(hours=offset) for offset in (3, 4, 5)])

    report = integrity(SYMBOL_A, "1h")

    assert report.missing == 3
    assert len(report.gaps) == 1
    assert report.gaps[0].start == start + timedelta(hours=3)
    assert report.gaps[0].end == start + timedelta(hours=6)
    assert report.gaps[0].missing == 3


def test_integrity_of_an_empty_symbol_is_all_zero(market_port) -> None:
    report = integrity("XNVDA-USDT", "1h")

    assert report.start is None
    assert report.end is None
    assert report.expected == 0
    assert report.present == 0
    assert report.missing == 0
    assert report.gaps == ()
    assert report.duplicates == ()


def test_integrity_flags_the_same_open_time_from_two_sources(market_port) -> None:
    """同一周期同一时刻被两个来源各写一行，视为重复，必须报出来。"""

    open_time = WINDOW_END - timedelta(hours=1)
    upsert_candles([_bar(open_time), _bar(open_time, source="mirror")])

    assert integrity(SYMBOL_A, "1h").duplicates == (open_time,)
    assert integrity(SYMBOL_A, "1h", source="okx").duplicates == ()


# ------------------------------------------------------------------- 相关性


def test_correlation_aligns_two_symbols_on_open_time(market_port) -> None:
    _sync_window(market_port, SYMBOL_A, 10)
    _sync_window(market_port, SYMBOL_B, 10)

    result = correlation(SYMBOL_A, SYMBOL_B, "1h")

    assert result.sample_size == 10
    assert result.method == "pearson"
    assert result.bar == "1h"
    assert result.coefficient is not None
    assert -1.0 <= result.coefficient <= 1.0
    assert result.p_value is not None
    assert 0.0 <= result.p_value <= 1.0


def test_correlation_uses_only_overlapping_bars(market_port) -> None:
    _sync_window(market_port, SYMBOL_A, 10)
    _sync_window(market_port, SYMBOL_B, 4)

    assert correlation(SYMBOL_A, SYMBOL_B, "1h").sample_size == 4


def test_correlation_without_overlap_reports_no_sample(market_port) -> None:
    _sync_window(market_port, SYMBOL_A, 5, end=WINDOW_END - timedelta(hours=5))
    _sync_window(market_port, SYMBOL_B, 5)

    result = correlation(SYMBOL_A, SYMBOL_B, "1h")

    assert result.sample_size == 0
    assert result.coefficient is None
    assert result.p_value is None


def test_correlation_respects_the_requested_window(market_port) -> None:
    _sync_window(market_port, SYMBOL_A, 10)
    _sync_window(market_port, SYMBOL_B, 10)

    start = WINDOW_END - timedelta(hours=4)
    result = correlation(SYMBOL_A, SYMBOL_B, "1h", start=start, end=WINDOW_END)

    assert result.sample_size == len(expected_open_times(start, WINDOW_END, "1h", ASSET_TYPE)) == 4


def test_correlation_supports_spearman(market_port) -> None:
    _sync_window(market_port, SYMBOL_A, 10)
    _sync_window(market_port, SYMBOL_B, 10)

    result = correlation(SYMBOL_A, SYMBOL_B, "1h", method="spearman")

    assert result.method == "spearman"
    assert result.coefficient is not None


def test_correlation_rejects_the_same_symbol() -> None:
    with pytest.raises(ValidationError):
        correlation(SYMBOL_A, SYMBOL_A, "1h")


def test_correlation_rejects_an_unknown_method() -> None:
    with pytest.raises(ValidationError):
        correlation(SYMBOL_A, SYMBOL_B, "1h", method="kendall")


def test_correlation_rejects_an_unknown_bar(market_port) -> None:
    with pytest.raises(ValidationError):
        correlation(SYMBOL_A, SYMBOL_B, "3h")

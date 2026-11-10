"""bar 周期归一化与 K 线对齐/缺口纯函数（已知答案用例）。

覆盖两个保留模块：`app.shared.timeframe`（周期枚举与别名）与
`app.market.candles`（对齐、缺口、重复、乱序）。全部为纯函数，输入输出手算可验。
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.market.candles import (
    duplicate_open_times,
    expected_open_times,
    find_gaps,
    floor_open_time,
    out_of_order,
)
from app.shared.timeframe import (
    BAR_SECONDS,
    CANONICAL_BARS,
    ROLLING_BARS,
    bar_seconds,
    is_rolling_bar,
    normalize_bar,
    parse_bars,
)

# ---------------------------------------------------------------- timeframe


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1h", "1h"),
        ("1H", "1h"),
        ("60m", "1h"),
        ("1hour", "1h"),
        ("4H", "4h"),
        ("240m", "4h"),
        ("1D", "1d"),
        ("24h", "1d"),
        ("1m", "1m"),
        ("15m", "15m"),
        (" 5MIN ", "5m"),
    ],
)
def test_alias_normalization(raw: str, expected: str) -> None:
    assert normalize_bar(raw) == expected


def test_unsupported_bar_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported bar"):
        normalize_bar("8H")
    with pytest.raises(ValueError):
        normalize_bar("2h")
    with pytest.raises(ValueError):
        normalize_bar(None)  # type: ignore[arg-type]


def test_bar_seconds_and_rolling_set() -> None:
    assert bar_seconds("1h") == 3600
    assert bar_seconds("1d") == 86400
    assert bar_seconds("15M") == 900
    assert ROLLING_BARS == ("1m", "5m", "15m")
    assert is_rolling_bar("15M") is True
    assert is_rolling_bar("1H") is False
    assert is_rolling_bar("1d") is False
    assert set(BAR_SECONDS) == set(CANONICAL_BARS)


def test_parse_bars_dedupes_and_keeps_order() -> None:
    assert parse_bars("1h,1H,4h,1d") == ["1h", "4h", "1d"]
    assert parse_bars("1h, ,4h") == ["1h", "4h"]
    assert parse_bars("") == []
    assert parse_bars(["4H", "1h", "4h"]) == ["4h", "1h"]


# ------------------------------------------------------------------- candles

START = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)


def test_floor_open_time_aligns_to_bar_boundary() -> None:
    moment = datetime(2026, 11, 6, 13, 37, 12, tzinfo=UTC)
    assert floor_open_time(moment, "15m") == datetime(2026, 11, 6, 13, 30, tzinfo=UTC)
    assert floor_open_time(moment, "1h") == datetime(2026, 11, 6, 13, 0, tzinfo=UTC)
    assert floor_open_time(moment, "4h") == datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    # 已在边界上的时间戳不后退一格。
    assert floor_open_time(START, "1h") == START


def test_floor_open_time_uses_utc8_midnight_for_daily() -> None:
    # OKX 的 1D 以 UTC+8 零点为界：2026-11-05T16:00Z == 2026-11-06 00:00 (+08:00)。
    assert floor_open_time(datetime(2026, 11, 6, 3, 0, tzinfo=UTC), "1d") == datetime(
        2026, 11, 5, 16, 0, tzinfo=UTC
    )
    assert floor_open_time(datetime(2026, 11, 5, 15, 59, tzinfo=UTC), "1d") == datetime(
        2026, 11, 4, 16, 0, tzinfo=UTC
    )


def test_floor_open_time_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        floor_open_time(datetime(2026, 11, 6, 13, 0), "1h")


def test_expected_open_times_is_half_open_interval() -> None:
    assert expected_open_times(START, START + timedelta(hours=3), "1h") == [
        START,
        START + timedelta(hours=1),
        START + timedelta(hours=2),
    ]
    # end 落在半开区间外；start 不对齐时先补齐到下一个边界。
    skewed_start = START + timedelta(minutes=30)
    assert expected_open_times(skewed_start, START + timedelta(hours=1), "1h") == []


def test_find_gaps_merges_consecutive_missing_slots() -> None:
    actual = {START, START + timedelta(hours=3)}
    assert find_gaps(actual, START, START + timedelta(hours=4), "1h") == [
        (START + timedelta(hours=1), START + timedelta(hours=3))
    ]


def test_find_gaps_extends_trailing_run_to_window_end() -> None:
    end = START + timedelta(hours=3)
    # 末尾连续缺失：缺口终点是「最后一个期望时刻 + 一个周期」。
    assert find_gaps({START}, START, end, "1h") == [(START + timedelta(hours=1), end)]
    complete = [START, START + timedelta(hours=1), START + timedelta(hours=2)]
    assert find_gaps(complete, START, end, "1h") == []


def test_duplicate_open_times_reports_each_duplicate_once() -> None:
    later = START + timedelta(hours=1)
    assert duplicate_open_times([START, later, START, START, later]) == [START, later]
    assert duplicate_open_times([START, later]) == []


def test_out_of_order_detects_regression_and_equal_steps() -> None:
    later = START + timedelta(hours=1)
    assert out_of_order([START, later]) is False
    assert out_of_order([]) is False
    assert out_of_order([later, START]) is True
    assert out_of_order([START, START]) is True

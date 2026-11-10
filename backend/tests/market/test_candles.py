"""K 线对齐、缺口、重复、乱序的纯函数（已知答案用例）。

全部输入输出手算可验：日线的定界随资产所属市场（24/7 用 UTC+8 零点、美股用正常时段
开盘），缺口用半开窗口表达。
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.market import (
    duplicate_open_times,
    expected_open_times,
    find_gaps,
    floor_open_time,
    out_of_order,
)

START = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
CRYPTO = "crypto"
TOKENIZED_EQUITY = "tokenized_equity"


def test_floor_open_time_aligns_to_bar_boundary() -> None:
    moment = datetime(2026, 11, 6, 13, 37, 12, tzinfo=UTC)
    assert floor_open_time(moment, "15m", CRYPTO) == datetime(2026, 11, 6, 13, 30, tzinfo=UTC)
    assert floor_open_time(moment, "1h", CRYPTO) == datetime(2026, 11, 6, 13, 0, tzinfo=UTC)
    assert floor_open_time(moment, "4h", CRYPTO) == datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    # 已在边界上的时间戳不后退一格。
    assert floor_open_time(START, "1h", CRYPTO) == START


def test_floor_open_time_uses_utc8_midnight_for_247_assets() -> None:
    # 24/7 资产沿用 OKX 的 1D 边界：2026-11-05T16:00Z == 2026-11-06 00:00 (+08:00)。
    assert floor_open_time(datetime(2026, 11, 6, 3, 0, tzinfo=UTC), "1d", CRYPTO) == datetime(
        2026, 11, 5, 16, 0, tzinfo=UTC
    )
    assert floor_open_time(datetime(2026, 11, 5, 15, 59, tzinfo=UTC), "1d", CRYPTO) == datetime(
        2026, 11, 4, 16, 0, tzinfo=UTC
    )


def test_floor_open_time_uses_the_session_open_for_equity_assets() -> None:
    """代币化股票的日界是当日正常时段开盘（09:30 美东），不是 OKX 的 16:00 UTC。"""

    assert floor_open_time(
        datetime(2026, 11, 6, 18, 0, tzinfo=UTC), "1d", TOKENIZED_EQUITY
    ) == datetime(2026, 11, 6, 14, 30, tzinfo=UTC)
    # 开盘前仍在上一交易日的日界上。
    assert floor_open_time(
        datetime(2026, 11, 6, 12, 0, tzinfo=UTC), "1d", TOKENIZED_EQUITY
    ) == datetime(2026, 11, 5, 14, 30, tzinfo=UTC)


def test_floor_open_time_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        floor_open_time(datetime(2026, 11, 6, 13, 0), "1h", CRYPTO)


def test_expected_open_times_is_half_open_interval() -> None:
    assert expected_open_times(START, START + timedelta(hours=3), "1h", CRYPTO) == [
        START,
        START + timedelta(hours=1),
        START + timedelta(hours=2),
    ]
    # end 落在半开区间外；start 不对齐时先补齐到下一个边界。
    skewed_start = START + timedelta(minutes=30)
    assert expected_open_times(skewed_start, START + timedelta(hours=1), "1h", CRYPTO) == []


def test_find_gaps_merges_consecutive_missing_slots() -> None:
    actual = {START, START + timedelta(hours=3)}
    assert find_gaps(actual, START, START + timedelta(hours=4), "1h", CRYPTO) == [
        (START + timedelta(hours=1), START + timedelta(hours=3))
    ]


def test_find_gaps_extends_trailing_run_to_window_end() -> None:
    end = START + timedelta(hours=3)
    # 末尾连续缺失：缺口终点是「最后一个期望时刻 + 一个周期」。
    assert find_gaps({START}, START, end, "1h", CRYPTO) == [(START + timedelta(hours=1), end)]
    complete = [START, START + timedelta(hours=1), START + timedelta(hours=2)]
    assert find_gaps(complete, START, end, "1h", CRYPTO) == []


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

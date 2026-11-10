"""bar 周期归一化（已知答案用例）：周期枚举、别名与规范写法。

K 线的对齐/缺口/重复/乱序用例在 `tests/market/test_candles.py`。
"""

import pytest

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

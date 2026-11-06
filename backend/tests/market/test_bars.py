"""bar 归一化与 OKX 映射（AC1/AC3 的基础契约）。"""

import pytest

from app.adapters.okx.bars import OKX_BAR, from_okx_bar, to_okx_bar
from app.market.core.bars import (
    CANONICAL_BARS,
    ROLLING_BARS,
    bar_seconds,
    is_rolling_bar,
    normalize_bar,
    parse_bars,
)


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
    ],
)
def test_alias_normalization(raw: str, expected: str) -> None:
    assert normalize_bar(raw) == expected


def test_unsupported_bar_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported bar"):
        normalize_bar("8H")
    with pytest.raises(ValueError):
        normalize_bar("2h")


def test_bar_seconds_and_rolling_set() -> None:
    assert bar_seconds("1h") == 3600
    assert bar_seconds("1d") == 86400
    assert ROLLING_BARS == ("1m", "5m", "15m")
    assert is_rolling_bar("15M") is True
    assert is_rolling_bar("1H") is False
    assert is_rolling_bar("1d") is False


def test_parse_bars_dedupes_and_keeps_order() -> None:
    assert parse_bars("1h,1H,4h,1d") == ["1h", "4h", "1d"]
    assert parse_bars("") == []


def test_okx_mapping_is_total_and_has_no_8h() -> None:
    assert set(OKX_BAR) == set(CANONICAL_BARS)
    assert "8H" not in OKX_BAR.values()
    assert to_okx_bar("1h") == "1H"
    assert to_okx_bar("1d") == "1D"
    assert from_okx_bar("4H") == "4h"

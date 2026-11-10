"""周期映射：内部规范写法 ↔ 上游写法。"""

from __future__ import annotations

import pytest

from app.exchange.okx.bars import OKX_BARS, from_okx_bar, to_okx_bar


def test_every_canonical_bar_maps_to_upstream_spelling() -> None:
    assert OKX_BARS == {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "1h": "1H",
        "4h": "4H",
        "1d": "1D",
    }


@pytest.mark.parametrize(("internal", "upstream"), [("1h", "1H"), ("1H", "1H")])
def test_hour_spellings_map_to_single_upstream_value(internal: str, upstream: str) -> None:
    assert to_okx_bar(internal) == upstream


@pytest.mark.parametrize(
    ("internal", "upstream"),
    [("1d", "1D"), ("1D", "1D"), ("4h", "4H"), ("4H", "4H"), ("15m", "15m"), ("15M", "15m")],
)
def test_other_bars_map_both_spellings(internal: str, upstream: str) -> None:
    assert to_okx_bar(internal) == upstream


@pytest.mark.parametrize(
    ("upstream", "internal"),
    [("1H", "1h"), ("1h", "1h"), ("1D", "1d"), ("4H", "4h"), ("1m", "1m")],
)
def test_upstream_spelling_maps_back_to_canonical(upstream: str, internal: str) -> None:
    assert from_okx_bar(upstream) == internal


def test_round_trip_is_stable_for_canonical_bars() -> None:
    for canonical in OKX_BARS:
        assert from_okx_bar(to_okx_bar(canonical)) == canonical


@pytest.mark.parametrize("bar", ["2h", "1w", "", "hourly"])
def test_unsupported_bar_raises_value_error(bar: str) -> None:
    with pytest.raises(ValueError):
        to_okx_bar(bar)

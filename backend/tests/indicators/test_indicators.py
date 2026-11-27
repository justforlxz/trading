"""八个指标的已知答案与边界用例。"""

from decimal import Decimal

import pytest

from app.indicators import Series, compute

#: 全部内置指标，按注册表列出的顺序（字典序）。
_NAMES = [
    "atr",
    "bollinger",
    "change_24h",
    "close",
    "ema",
    "macd",
    "rsi",
    "sma",
    "volume",
    "volume_ma",
    "vwap",
]

#: 至少两根 K 线才可能有结果的那部分；收盘价与成交量一根就够，不在其中。
_WARMUP_NAMES = [name for name in _NAMES if name not in {"close", "volume"}]
_TOLERANCE = Decimal("1e-12")


def _values(series: Series, key: str) -> list[Decimal | None]:
    return [point.values[key] for point in series.points]


def _assert_number(actual: Decimal | None, expected: str) -> None:
    assert actual is not None
    assert abs(actual - Decimal(expected)) < _TOLERANCE


def test_sma_is_rolling_close_mean(make_bars) -> None:
    series = compute("sma", make_bars(range(1, 6)), {"period": 3})

    assert _values(series, "sma") == [None, None, Decimal(2), Decimal(3), Decimal(4)]


def test_ema_seeds_with_sma_then_weights(make_bars) -> None:
    series = compute("ema", make_bars(range(1, 6)), {"period": 3})

    assert _values(series, "ema") == [None, None, Decimal(2), Decimal(3), Decimal(4)]


def test_rsi_uses_wilder_smoothing(make_bars) -> None:
    series = compute("rsi", make_bars([1, 2, 1, 2]), {"period": 2})

    assert _values(series, "rsi")[:2] == [None, None]
    _assert_number(_values(series, "rsi")[2], "50")
    _assert_number(_values(series, "rsi")[3], "75")


def test_rsi_without_losses_pins_at_one_hundred(make_bars) -> None:
    series = compute("rsi", make_bars(range(1, 17)), {"period": 14})

    assert _values(series, "rsi")[:14] == [None] * 14
    assert _values(series, "rsi")[14:] == [Decimal(100), Decimal(100)]


def test_rsi_flat_series_has_no_direction(make_bars) -> None:
    series = compute("rsi", make_bars([5] * 16), {"period": 14})

    assert _values(series, "rsi")[14:] == [None, None]


def test_macd_known_lines(make_bars) -> None:
    series = compute("macd", make_bars(range(1, 7)), {"fast": 2, "slow": 3, "signal": 2})

    assert _values(series, "macd")[:2] == [None, None]
    for value in _values(series, "macd")[2:]:
        _assert_number(value, "0.5")

    assert _values(series, "signal")[:3] == [None, None, None]
    for value in _values(series, "signal")[3:]:
        _assert_number(value, "0.5")

    assert _values(series, "hist")[:3] == [None, None, None]
    for value in _values(series, "hist")[3:]:
        _assert_number(value, "0")


def test_atr_uses_true_range_and_wilder_average(make_bars) -> None:
    bars = make_bars(
        [10, 11, 12, 11],
        highs=[11, 12, 14, 13],
        lows=[9, 10, 11, 10],
    )
    series = compute("atr", bars, {"period": 3})

    assert _values(series, "atr")[:2] == [None, None]
    _assert_number(_values(series, "atr")[2], "2.333333333333333333333333333")
    _assert_number(_values(series, "atr")[3], "2.555555555555555555555555556")


def test_bollinger_bands_use_population_std(make_bars) -> None:
    series = compute("bollinger", make_bars(range(1, 6)), {"period": 3, "num_std": 2})

    assert _values(series, "middle") == [None, None, Decimal(2), Decimal(3), Decimal(4)]
    assert _values(series, "upper")[:2] == [None, None]
    assert _values(series, "lower")[:2] == [None, None]
    _assert_number(_values(series, "upper")[2], "3.632993161855452065464856050")
    _assert_number(_values(series, "lower")[2], "0.367006838144547934535143950")


def test_vwap_weights_typical_price_by_volume(make_bars) -> None:
    bars = make_bars([10, 20], highs=[11, 22], lows=[9, 18], volumes=[1, 3])
    series = compute("vwap", bars, {"period": 2})

    assert _values(series, "vwap")[0] is None
    assert _values(series, "vwap")[1] == Decimal("17.5")


def test_vwap_window_without_volume_is_undefined(make_bars) -> None:
    bars = make_bars([10, 20], volumes=[0, 0])
    series = compute("vwap", bars, {"period": 2})

    assert _values(series, "vwap") == [None, None]


def test_volume_ma_is_rolling_volume_mean(make_bars) -> None:
    series = compute("volume_ma", make_bars([1, 2, 3], volumes=[1, 2, 3]), {"period": 2})

    assert _values(series, "volume_ma") == [None, Decimal("1.5"), Decimal("2.5")]


def test_close_is_the_bar_close(make_bars) -> None:
    series = compute("close", make_bars([10, 11, 12]))

    assert _values(series, "close") == [Decimal(10), Decimal(11), Decimal(12)]


def test_volume_is_the_bar_volume(make_bars) -> None:
    series = compute("volume", make_bars([10, 11], volumes=[3, 4]))

    assert _values(series, "volume") == [Decimal(3), Decimal(4)]


def test_change_24h_on_daily_bars_compares_the_previous_close(make_bars) -> None:
    """日线上 24 小时就是一根 K 线：与前一根收盘价比，单位是百分比。"""

    series = compute("change_24h", make_bars([10, 10, 11], bar="1d"))

    assert _values(series, "change_24h") == [None, Decimal(0), Decimal(10)]


def test_change_24h_on_hourly_bars_looks_24_bars_back(make_bars) -> None:
    """小时线上 24 小时是 24 根：第 24 根与第 0 根比。"""

    series = compute("change_24h", make_bars([10] * 24 + [11, 12], bar="1h"))

    values = _values(series, "change_24h")
    assert values[:24] == [None] * 24
    assert values[24] == Decimal(10)
    assert values[25] == Decimal(20)


def test_change_24h_without_a_full_day_is_undefined(make_bars) -> None:
    """凑不满 24 小时就没有基期：序列仍然与 K 线对齐，但每点都是 None。"""

    series = compute("change_24h", make_bars([10, 11, 12], bar="1h"))

    assert len(series.points) == 3
    assert _values(series, "change_24h") == [None, None, None]


def test_change_24h_with_a_zero_base_is_undefined(make_bars) -> None:
    """基期收盘价为 0 时涨跌幅没有定义，不返回一个假数字。"""

    series = compute("change_24h", make_bars([0, 5], bar="1d"))

    assert _values(series, "change_24h") == [None, None]


@pytest.mark.parametrize("name", _WARMUP_NAMES)
def test_single_bar_yields_no_points(name: str, make_bars) -> None:
    series = compute(name, make_bars(["10"]))

    assert series.points == ()

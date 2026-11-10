"""指标注册表与门面的行为契约。"""

from decimal import Decimal

import pytest

from app.core import ValidationError
from app.indicators import (
    IndicatorDefinition,
    Param,
    ParamValue,
    Point,
    Series,
    compute,
    definition,
    list_definitions,
)

_NAMES = ["atr", "bollinger", "ema", "macd", "rsi", "sma", "volume_ma", "vwap"]
_BAR_FIELDS = frozenset({"open", "high", "low", "close", "volume"})


def test_lists_every_builtin_indicator() -> None:
    definitions = list_definitions()

    assert [item.name for item in definitions] == _NAMES
    assert all(isinstance(item, IndicatorDefinition) for item in definitions)


def test_each_definition_declares_contract() -> None:
    for spec in list_definitions():
        assert spec.title
        assert spec.summary
        assert spec.outputs
        assert spec.inputs
        assert set(spec.inputs) <= _BAR_FIELDS
        assert spec.min_length >= 1
        for param in spec.params:
            assert isinstance(param, Param)
            assert param.kind in {"int", "float"}
            assert param.minimum <= param.default <= param.maximum


def test_definition_lookup_returns_declared_metadata() -> None:
    spec = definition("rsi")

    assert spec.name == "rsi"
    assert spec.inputs == ("close",)
    assert spec.outputs == ("rsi",)
    assert spec.min_length == 15
    assert [(param.name, param.kind) for param in spec.params] == [("period", "int")]
    assert spec.params[0].default == 14


def test_unknown_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        definition("vwap_2")
    with pytest.raises(ValidationError):
        compute("vwap_2", [])


def test_defaults_fill_the_whole_param_table(make_bars) -> None:
    series = compute("macd", make_bars(range(1, 41)))
    params: dict[str, ParamValue] = series.params

    assert isinstance(series, Series)
    assert params == {"fast": 12, "slow": 26, "signal": 9}


def test_explicit_params_override_defaults(make_bars) -> None:
    series = compute("sma", make_bars(range(1, 6)), {"period": 3})

    assert series.params == {"period": 3}
    assert series.points[2].values["sma"] == Decimal(2)


def test_unknown_param_is_rejected(make_bars) -> None:
    with pytest.raises(ValidationError, match="不支持参数"):
        compute("sma", make_bars(range(1, 21)), {"window": 5})


@pytest.mark.parametrize(
    ("name", "params"),
    [
        ("sma", {"period": 0}),
        ("sma", {"period": 501}),
        ("bollinger", {"num_std": 0.05}),
        ("bollinger", {"num_std": 11.0}),
    ],
)
def test_out_of_range_param_is_rejected(name: str, params: dict[str, ParamValue]) -> None:
    with pytest.raises(ValidationError, match="必须在"):
        compute(name, [], params)


@pytest.mark.parametrize(
    ("name", "params"),
    [
        ("sma", {"period": "20"}),
        ("sma", {"period": True}),
        ("sma", {"period": 20.0}),
        ("bollinger", {"num_std": "2.0"}),
        ("bollinger", {"num_std": True}),
    ],
)
def test_param_type_is_enforced(name: str, params: dict[str, ParamValue]) -> None:
    with pytest.raises(ValidationError, match="必须是"):
        compute(name, [], params)


def test_macd_rejects_fast_not_below_slow(make_bars) -> None:
    bars = make_bars(range(1, 41))

    with pytest.raises(ValidationError, match="fast"):
        compute("macd", bars, {"fast": 26, "slow": 26})
    with pytest.raises(ValidationError, match="fast"):
        compute("macd", bars, {"fast": 30, "slow": 26})


@pytest.mark.parametrize("name", _NAMES)
def test_history_below_min_length_yields_no_points(name: str, make_bars) -> None:
    spec = definition(name)
    series = compute(name, make_bars(range(1, spec.min_length)))

    assert series.points == ()
    assert series.name == name
    assert series.params


@pytest.mark.parametrize("name", _NAMES)
def test_empty_history_yields_no_points(name: str) -> None:
    series = compute(name, [])

    assert isinstance(series, Series)
    assert series.points == ()


def test_points_follow_bar_times(make_bars) -> None:
    bars = make_bars(range(1, 21))
    series = compute("sma", bars)

    assert len(series.points) == len(bars)
    assert [point.time for point in series.points] == [bar.open_time for bar in bars]
    assert isinstance(series.points[0], Point)


@pytest.mark.parametrize("name", _NAMES)
def test_points_carry_exactly_the_declared_outputs(name: str, make_bars) -> None:
    spec = definition(name)
    bars = make_bars(range(1, spec.min_length + 5))
    series = compute(name, bars)

    assert len(series.points) == len(bars)
    for point in series.points:
        assert tuple(point.values) == spec.outputs


def test_compute_is_pure(make_bars) -> None:
    bars = make_bars(range(1, 41))

    first = compute("atr", bars)
    second = compute("atr", bars)

    assert first == second
    assert first is not second
    assert first.points[0] is not second.points[0]

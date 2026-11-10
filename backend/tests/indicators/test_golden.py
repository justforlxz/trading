"""与外部已知答案比对：golden 文件里的 RSI 与测试内独立的 EMA 实现。"""

import json
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from app.indicators import compute

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "indicators"
_TOLERANCE = Decimal("1e-9")


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def test_rsi14_matches_golden_file(make_bars) -> None:
    golden = _load("rsi14.json")
    series = compute("rsi", make_bars(golden["closes"]), {"period": golden["period"]})

    actual = [point.values["rsi"] for point in series.points]
    assert len(actual) == len(golden["values"])
    for value, expected in zip(actual, golden["values"], strict=True):
        if expected is None:
            assert value is None
            continue
        assert value is not None
        assert abs(value - Decimal(expected)) < _TOLERANCE


def test_ema_matches_independent_fraction_implementation(make_bars) -> None:
    closes = _load("rsi14.json")["closes"]
    period = 12
    series = compute("ema", make_bars(closes), {"period": period})
    expected = _fraction_ema([Fraction(item) for item in closes], period)

    for point, reference in zip(series.points, expected, strict=True):
        value = point.values["ema"]
        if reference is None:
            assert value is None
            continue
        assert value is not None
        assert (
            abs(value - Decimal(reference.numerator) / Decimal(reference.denominator)) < _TOLERANCE
        )


def _fraction_ema(values: list[Fraction], period: int) -> list[Fraction | None]:
    """朴素递推：首值取前 `period` 个的算术平均，之后每点按 `2/(n+1)` 加权。"""

    alpha = Fraction(2, period + 1)
    previous = sum(values[:period]) / period
    column: list[Fraction | None] = [None] * (period - 1)
    column.append(previous)
    for value in values[period:]:
        previous = alpha * value + (1 - alpha) * previous
        column.append(previous)
    return column

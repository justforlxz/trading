"""全市场特征截面纯函数单测（P1-11）：手算对拍与「未定义不用 0 冒充」。"""

import math
from datetime import UTC, datetime, timedelta

import pytest

from app.analysis.core import features

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def bars_from(closes: list[float], volumes: list[float] | None = None) -> list[features.Bar]:
    volumes = volumes or [1000.0] * len(closes)
    return [
        features.Bar(
            open_time=BASE + timedelta(days=index),
            high=close + 1.0,
            low=close - 1.0,
            close=close,
            vol=volumes[index],
        )
        for index, close in enumerate(closes)
    ]


def test_total_return_matches_hand_calculation() -> None:
    closes = [10.0, 11.0, 12.0]
    assert features.total_return(closes, 1) == pytest.approx(12.0 / 11.0 - 1.0)
    assert features.total_return(closes, 2) == pytest.approx(0.2)


def test_total_return_needs_enough_samples_and_positive_prices() -> None:
    assert features.total_return([10.0, 11.0], 2) is None
    assert features.total_return([10.0, 0.0], 1) is None


def test_log_returns_and_volatility() -> None:
    closes = [100.0, 101.0, 100.0, 102.0]
    returns = features.log_returns(closes)
    assert returns is not None
    assert returns == pytest.approx(
        [math.log(1.01), math.log(100 / 101), math.log(1.02)], abs=1e-15
    )
    # 窗口比样本多 → 未定义，不返回 0。
    assert features.volatility(closes, window=4) is None
    assert features.volatility(closes, window=2) is not None


def test_volatility_is_none_for_constant_prices() -> None:
    assert features.volatility([10.0, 10.0, 10.0, 10.0]) is None


def test_average_true_range_uses_simple_mean() -> None:
    bars = bars_from([10.0, 12.0, 11.0])
    ranges = features.true_ranges(bars)
    # 第一根没有前收 → high - low；之后取三者最大。
    assert ranges == [pytest.approx(2.0), pytest.approx(3.0), pytest.approx(2.0)]
    assert features.average_true_range(bars, window=3) == pytest.approx(7.0 / 3.0)


def test_volume_z_flags_abnormal_volume_and_rejects_zero_variance() -> None:
    assert features.volume_z([100.0] * 20) is None
    values = [100.0] * 19 + [200.0]
    assert features.volume_z(values, window=20) is not None


def test_cross_section_reports_undefined_without_faking_zero() -> None:
    empty = features.cross_section([])
    assert empty.defined is False
    assert empty.ret_1d is None
    assert empty.bars == 0

    single = features.cross_section(bars_from([10.0]))
    assert single.defined is False
    assert single.ret_1d is None
    assert single.high_20d == pytest.approx(11.0)


def test_cross_section_computes_all_windows() -> None:
    closes = [100.0 + index for index in range(30)]
    section = features.cross_section(bars_from(closes))
    assert section.bars == 30
    assert section.ret_1d == pytest.approx(129.0 / 128.0 - 1.0)
    assert section.ret_5d == pytest.approx(129.0 / 124.0 - 1.0)
    assert section.ret_20d == pytest.approx(129.0 / 109.0 - 1.0)
    assert section.high_20d == pytest.approx(129.0 + 1.0)
    # 最近 20 根是 110..129，最低收盘 110，故最低价 109。
    assert section.low_20d == pytest.approx(109.0)

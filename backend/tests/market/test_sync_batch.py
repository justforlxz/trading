"""批量读 K 线：与逐个标的读取逐项相同。

批量读是本任务的提速手段，语义必须与 `load_candles` / `latest_candle` 完全一致：
同一标的的多来源分开成组，缺 K 线的标的不出现在结果里，`latest` 仍不限定周期。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core import Bar, Timeframe, ValidationError
from app.market import (
    latest_candle,
    latest_candles_by_source,
    load_candles,
    load_candles_by_source,
    upsert_candles,
)

DAY = timedelta(days=1)
START = datetime(2026, 10, 1, 16, 0, tzinfo=UTC)
D = Decimal


def _daily(symbol: str, closes: list[str], *, source: str = "okx") -> None:
    """写入连续日线（每天 16:00 UTC 开盘），四个价格取同一个收盘值。"""

    upsert_candles(
        [
            Bar(
                inst_id=symbol,
                timeframe=Timeframe.parse("1d"),
                open_time=START + DAY * index,
                open=D(close),
                high=D(close),
                low=D(close),
                close=D(close),
                volume=D("10"),
                confirm=True,
                source=source,
            )
            for index, close in enumerate(closes)
        ]
    )


def _hourly(symbol: str, open_time: datetime, *, close: str, source: str = "okx") -> None:
    upsert_candles(
        [
            Bar(
                inst_id=symbol,
                timeframe=Timeframe.parse("1h"),
                open_time=open_time,
                open=D(close),
                high=D(close),
                low=D(close),
                close=D(close),
                volume=D("1"),
                confirm=True,
                source=source,
            )
        ]
    )


def _seed_mixed_sources() -> None:
    """三个标的：多根日线、混合来源（同一标的两种来源）、只有一根日线。"""

    _daily("XAAPL-USDT", ["100", "110", "120"])
    _daily("XAAPL-USDT", ["101", "111"], source="yahoo")
    _daily("ETH-USDT", ["2000"])


def test_load_candles_by_source_matches_per_symbol_reads() -> None:
    _seed_mixed_sources()

    grouped = load_candles_by_source(["XAAPL-USDT", "ETH-USDT", "NONE-USDT"], "1d")

    assert grouped[("XAAPL-USDT", "okx")] == load_candles("XAAPL-USDT", "1d", source="okx")
    assert grouped[("XAAPL-USDT", "yahoo")] == load_candles("XAAPL-USDT", "1d", source="yahoo")
    assert grouped[("ETH-USDT", "okx")] == load_candles("ETH-USDT", "1d", source="okx")
    # 没有 K 线的标的不出现在结果里，与 `load_candles` 返回空列表对应。
    assert [key for key in grouped if key[0] == "NONE-USDT"] == []
    assert load_candles("NONE-USDT", "1d") == []


def test_load_candles_by_source_keeps_sources_apart() -> None:
    """同一标的混存两种来源时分别成组，不合并成一条时间轴。"""

    _seed_mixed_sources()

    grouped = load_candles_by_source(["XAAPL-USDT"], "1d")

    assert sorted(grouped) == [("XAAPL-USDT", "okx"), ("XAAPL-USDT", "yahoo")]
    assert len(grouped[("XAAPL-USDT", "okx")]) == 3
    assert len(grouped[("XAAPL-USDT", "yahoo")]) == 2


def test_load_candles_by_source_honours_source_filter() -> None:
    _seed_mixed_sources()

    grouped = load_candles_by_source(["XAAPL-USDT"], "1d", sources=["yahoo"])

    assert list(grouped) == [("XAAPL-USDT", "yahoo")]


def test_load_candles_by_source_returns_empty_for_no_symbols() -> None:
    assert load_candles_by_source([], "1d") == {}
    assert load_candles_by_source(["XAAPL-USDT"], "1d", sources=[]) == {}


def test_load_candles_by_source_rejects_unknown_bar() -> None:
    with pytest.raises(ValidationError):
        load_candles_by_source(["XAAPL-USDT"], "3d")


def test_latest_candles_by_source_matches_per_symbol_reads() -> None:
    """最新一根不限定周期：1h 比日线更新时，取到的是那根 1h。"""

    _seed_mixed_sources()
    newest_day = START + DAY * 4
    _hourly("XAAPL-USDT", newest_day + timedelta(minutes=30), close="130")

    latest = latest_candles_by_source(["XAAPL-USDT", "ETH-USDT"], sources=["okx", "yahoo"])

    for symbol in ("XAAPL-USDT", "ETH-USDT"):
        for source in ("okx", "yahoo"):
            assert latest.get((symbol, source)) == latest_candle(symbol, source=source)
    assert latest[("XAAPL-USDT", "okx")].close == D("130")
    assert latest[("XAAPL-USDT", "okx")].timeframe == Timeframe.parse("1h")


def test_latest_candles_by_source_honours_source_filter() -> None:
    _seed_mixed_sources()

    latest = latest_candles_by_source(["XAAPL-USDT"], sources=["okx"])

    assert list(latest) == [("XAAPL-USDT", "okx")]
    assert latest[("XAAPL-USDT", "okx")].close == D("120")


def test_latest_candles_by_source_returns_empty_for_no_symbols() -> None:
    assert latest_candles_by_source([]) == {}

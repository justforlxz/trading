"""指标测试共用的 K 线工厂。"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core import Bar, Timeframe

_START = datetime(2026, 1, 1, tzinfo=UTC)
_DEFAULT_VOLUME = Decimal(1000)


def _decimal(value: Decimal | float | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _build(
    closes: Sequence[Decimal | float | str],
    *,
    highs: Sequence[Decimal | float | str] | None = None,
    lows: Sequence[Decimal | float | str] | None = None,
    volumes: Sequence[Decimal | float | str] | None = None,
    bar: str = "1h",
) -> list[Bar]:
    """按收盘价造 K 线；未指定的高低价默认收盘价上下各 1，成交量默认 1000。"""

    timeframe = Timeframe.parse(bar)
    bars: list[Bar] = []
    for index, raw_close in enumerate(closes):
        close = _decimal(raw_close)
        high = _decimal(highs[index]) if highs is not None else close + 1
        low = _decimal(lows[index]) if lows is not None else close - 1
        volume = _decimal(volumes[index]) if volumes is not None else _DEFAULT_VOLUME
        bars.append(
            Bar(
                inst_id="BTC-USDT",
                timeframe=timeframe,
                open_time=_START + index * timedelta(seconds=timeframe.seconds),
                open=close,
                high=high,
                low=low,
                close=close,
                volume=volume,
                confirm=True,
                source="test",
            )
        )
    return bars


@pytest.fixture(name="make_bars")
def make_bars_fixture() -> Callable[..., list[Bar]]:
    return _build

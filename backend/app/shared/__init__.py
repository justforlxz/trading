"""时序基础模块：被 market / backtest 等域共享的纯函数。

门面即出口：跨包只允许 `from app.shared import ...`。
"""

from app.shared.timeframe import (
    BAR_SECONDS,
    CANONICAL_BARS,
    ROLLING_BARS,
    bar_seconds,
    is_rolling_bar,
    normalize_bar,
    parse_bars,
)

__all__ = [
    "BAR_SECONDS",
    "CANONICAL_BARS",
    "ROLLING_BARS",
    "bar_seconds",
    "is_rolling_bar",
    "normalize_bar",
    "parse_bars",
]

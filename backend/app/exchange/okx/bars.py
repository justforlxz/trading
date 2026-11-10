"""周期字符串双向映射：内部规范写法 ↔ 上游写法。

内部周期枚举固定在 `app.shared.timeframe`（`1m/5m/15m/1h/4h/1d`）。上游要求
`H`/`D` 大写，小写会直接被判参数错误，因此这个映射只能出现在交易所适配层。
"""

from __future__ import annotations

from app.shared import normalize_bar

__all__ = ["OKX_BARS", "from_okx_bar", "to_okx_bar"]

# 内部规范周期 → 上游写法。
OKX_BARS: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1H",
    "4h": "4H",
    "1d": "1D",
}


def to_okx_bar(bar: str) -> str:
    """内部周期（`1h` 与 `1H` 都接受）→ 上游写法。

    不支持的周期由 `normalize_bar` 抛 `ValueError`。
    """

    return OKX_BARS[normalize_bar(bar)]


def from_okx_bar(bar: str) -> str:
    """上游写法 → 内部规范周期。"""

    return normalize_bar(bar)

"""上游解析出的一根 K 线，尚未按市场规则定界。

单独一个模块是为了避免「实现 ← 注册表 → 实现」的循环导入：注册表在
`app.exchange.providers` 里导入各实现，实现只能从本模块拿 `RawBar`。

`open_time` 是上游自己给的时刻（带时区）。日线源给的是「交易日内的某个固定时刻」，
不是自然日零点——把日期表达成时刻需要一个锚点，定界由行情域算（`app/equity/providers.py`）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

__all__ = ["RawBar"]


@dataclass(frozen=True, slots=True)
class RawBar:
    """一根上游 K 线：标的、上游时刻与 OHLCV。"""

    symbol: str
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

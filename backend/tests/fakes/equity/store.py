"""假美股代理行情的报文：与上游 chart 接口同形状，数值由代码与开盘时刻派生。

行情只落在周一至周五，开盘时刻固定 14:30 UTC（美东 09:30 的冬令时写法）；测试
不校验夏令时换算，只校验「日线边界落在交易时段」这一事实。

复权收盘价刻意不等于原始收盘价（默认乘一个固定因子），分红与拆股事件放在请求
窗口内：适配器若取错列或忽略复权，断言立刻变红。

价格与成交量按上游的真实形态给出：先取到分位，再过一遍 float32 ——真实上游返回的
就是这种带长尾的浮点（`338.7300109863281`），13-14 位小数。夹具照搬这一点，
适配器若把浮点原样写进 `Decimal`，K 线接口按契约序列化时就会 500。
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

__all__ = ["FIXED_LAST_DAY", "FakeEquity", "daily_open", "previous_trading_day"]

# 最后一根日线的交易日：周二，避开周末与「休市日表没有该年」的问题。
FIXED_LAST_DAY = date(2026, 11, 10)

# 美东 09:30 开盘的冬令时写法；夏令时是 13:30 UTC，本夹具不模拟切换。
DAILY_OPEN_UTC = time(14, 30)

# 常规时段长度（9:30-16:00，6.5 小时）。
SESSION_SECONDS = 6 * 3600 + 1800

# 复权因子：与原始收盘价的比值，用于分辨「取了复权列」还是「取了原始列」。
ADJUSTMENT_RATIO = Decimal("0.9")

_CENT = Decimal("0.01")
_ONE_DAY = timedelta(days=1)


def daily_open(day: date) -> int:
    """某个交易日的日线开盘时刻（epoch 秒）。"""

    return int(datetime.combine(day, DAILY_OPEN_UTC, tzinfo=UTC).timestamp())


def previous_trading_day(day: date) -> date:
    """前一个交易日（跳过周六周日）。"""

    cursor = day - _ONE_DAY
    while cursor.weekday() >= 5:
        cursor -= _ONE_DAY
    return cursor


def _upstream(value: Decimal) -> float:
    """分位价格 → 上游浮点：过一遍 float32，复现真实上游的 13-14 位小数长尾。"""

    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def _seed(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _price(*parts: object) -> Decimal:
    """10.00 ~ 1009.99 之间的确定性价格。"""

    return (_seed(*parts) % 100_000 / Decimal(100) + Decimal(10)).quantize(_CENT)


@dataclass(frozen=True, slots=True)
class _Row:
    """一根日线的原始数值：原始收盘与复权收盘不同，成交量固定可断言。"""

    open_time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adj_close: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class FakeEquity:
    """一个代码的日线序列与上游应答形状。

    `in_session=True` 时最后一根是「当前交易时段内、尚未收盘」的 bar：`meta` 的
    当前时段从这根开始、`regularMarketTime` 落在时段中间，适配器必须把它标成未收盘。
    """

    ticker: str = "AAPL"
    count: int = 10
    last_day: date = FIXED_LAST_DAY
    in_session: bool = False
    with_events: bool = True
    with_adjusted_close: bool = True
    _rows: tuple[_Row, ...] = field(init=False, repr=False, default=())

    def __post_init__(self) -> None:
        object.__setattr__(self, "_rows", self._build_rows())

    @property
    def open_times(self) -> list[int]:
        """升序的日线开盘时刻（epoch 秒）。"""

        return [row.open_time for row in self._rows]

    def chart(self, *, period1: int, period2: int) -> dict[str, Any]:
        """返回窗口 `[period1, period2)` 内的完整应答封包（`{"chart": {...}}`）。"""

        rows = [row for row in self._rows if period1 <= row.open_time < period2]
        indicator: dict[str, Any] = {
            "quote": [
                {
                    "open": [_upstream(row.open) for row in rows],
                    "high": [_upstream(row.high) for row in rows],
                    "low": [_upstream(row.low) for row in rows],
                    "close": [_upstream(row.close) for row in rows],
                    "volume": [_upstream(row.volume) for row in rows],
                }
            ]
        }
        if self.with_adjusted_close:
            indicator["adjclose"] = [{"adjclose": [_upstream(row.adj_close) for row in rows]}]
        result: dict[str, Any] = {
            "meta": self._meta(),
            "timestamp": [row.open_time for row in rows],
            "indicators": indicator,
        }
        events = self._events(rows)
        if events:
            result["events"] = events
        return {"chart": {"result": [result], "error": None}}

    def error(self, *, code: str, description: str) -> dict[str, Any]:
        """上游的「查不到这个代码」应答：HTTP 200，`result` 为空、`error` 有内容。"""

        return {"chart": {"result": None, "error": {"code": code, "description": description}}}

    def _build_rows(self) -> tuple[_Row, ...]:
        days: list[date] = []
        cursor = self.last_day
        while len(days) < self.count:
            days.append(cursor)
            cursor = previous_trading_day(cursor)
        rows: list[_Row] = []
        for day in reversed(days):
            open_time = daily_open(day)
            close = _price(self.ticker, open_time)
            rows.append(
                _Row(
                    open_time=open_time,
                    open=_price(self.ticker, open_time, "open"),
                    high=_price(self.ticker, open_time, "high") + Decimal("1.00"),
                    low=_price(self.ticker, open_time, "low"),
                    close=close,
                    adj_close=(close * ADJUSTMENT_RATIO).quantize(_CENT),
                    volume=Decimal("1234500"),
                )
            )
        return tuple(rows)

    def _meta(self) -> dict[str, Any]:
        """当前时段与最近成交时刻：适配器据此判断哪一根还没收盘。"""

        if self.in_session:
            # 盘中：最后一根就是当前时段，最近成交停在时段中间。
            session_start = daily_open(self.last_day)
            last_trade = session_start + 60
        else:
            # 收盘后：当前时段是下一个交易日，最近成交停在上一时段收盘时刻。
            session_start = daily_open(previous_trading_day(self.last_day))
            last_trade = session_start + SESSION_SECONDS
        session_end = session_start + SESSION_SECONDS
        return {
            "currency": "USD",
            "symbol": self.ticker,
            "exchangeName": "NMS",
            "instrumentType": "EQUITY",
            "regularMarketTime": last_trade,
            "currentTradingPeriod": {
                "pre": {"start": session_start - SESSION_SECONDS, "end": session_start},
                "regular": {"start": session_start, "end": session_end},
                "post": {"start": session_end, "end": session_end + SESSION_SECONDS},
            },
        }

    def _events(self, rows: list[_Row]) -> dict[str, Any]:
        """分红与拆股：都落在本次窗口内，供「只用复权收盘价」的断言使用。"""

        if not self.with_events or len(rows) < 2:
            return {}
        dividend_at = rows[-2].open_time
        split_at = rows[-1].open_time
        return {
            "dividends": {str(dividend_at): {"amount": 0.25, "date": dividend_at}},
            "splits": {
                str(split_at): {
                    "date": split_at,
                    "numerator": 4.0,
                    "denominator": 1.0,
                    "splitRatio": "4:1",
                }
            },
        }

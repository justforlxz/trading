"""Stooq CSV：只有日线，免费、无需 key，作为备用源。

`GET {url}` 的 `{symbol}` 由配置里的地址模板替换（`...?s={symbol}.us&i=d`，市场后缀
写在模板里），返回 `Date,Open,High,Low,Close,Volume` 的 CSV，一行一个交易日。

**实测（2026-11-22，本机）**：`https://stooq.com/q/d/l/?s=spy.us&i=d` 与
`https://stooq.pl/...` 都返回一段需要 JavaScript 求解的挑战页（HTTP 200 + HTML），
不是 CSV。因此本实现在真实网络下拿不到数据，端到端验证用本地替身（见
`tests/exchange/test_equity_providers.py`）；解析与窗口过滤按 Stooq 公布的 CSV 格式
实现，上游放开后即可直接用。

日线的日期需要一个时刻锚点才能装进 `RawBar`：取该交易日美东正常时段内的固定时刻
（16:00 UTC = 11:00–12:00 美东），具体定界（09:30 美东开盘）由行情域按市场规则算。
用 UTC 午夜当锚点会让日期落到美东的前一天。
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core import UpstreamError
from app.exchange.providers.http import get_text
from app.exchange.providers.raw import RawBar

__all__ = ["StooqSource", "parse_stooq"]

#: 日期锚点：美股正常时段内的固定时刻。16:00 UTC 在美东是 11:00–12:00，
#: 夏令时切换也不会跨日，因此「这个日期属于哪一天」不会算错。
_SESSION_ANCHOR_UTC = time(16, 0)


def _url_for(options: Mapping[str, Any], symbol: str) -> str:
    template = options.get("url")
    template = template.strip() if isinstance(template, str) else ""
    if not template:
        raise UpstreamError("Stooq 行情源未配置上游地址")
    # Stooq 的代码是小写 + 市场后缀，后缀写在地址模板里。
    return template.replace("{symbol}", symbol.strip().lower())


def _decimal(value: str | None) -> Decimal | None:
    """上游文本 → `Decimal`；空串表示「这一行没有这个值」，不是 0。"""

    if value is None or not value.strip():
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation:
        return None


def _day(value: str | None) -> date | None:
    """`YYYY-MM-DD` → 日期；格式不对时给 `None`，不猜一天出来。"""

    if not value or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


class StooqSource:
    """Stooq 日线 CSV：`delayed=True`（收盘后才发布的日结数据，不是实时）。"""

    name = "stooq"
    bar = "1d"
    #: 日结数据在收盘后才发布，任何时刻都不能当作实时报价。
    delayed = True

    def __init__(self, *, options: Mapping[str, Any], client: httpx.Client | None = None) -> None:
        self._options = options
        self._client = client

    def supports(self, symbols: Sequence[str]) -> bool:
        return all(item.strip() for item in symbols)

    def url_for(self, symbol: str) -> str:
        """该标的的真实请求地址（代码小写 + 市场后缀）；接口显示来源链接时用它。"""

        return _url_for(self._options, symbol)

    def fetch(self, symbols: Sequence[str], start: datetime, end: datetime) -> list[RawBar]:
        bars: list[RawBar] = []
        for symbol in symbols:
            text = get_text(_url_for(self._options, symbol), self._client)
            bars.extend(parse_stooq(text, symbol, start=start, end=end))
        return bars


def parse_stooq(text: str, symbol: str, *, start: datetime, end: datetime) -> list[RawBar]:
    """Stooq CSV → 窗口内的日线；非 CSV（例如挑战页）如实报上游错误。"""

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or not {"Date", "Close"} <= set(reader.fieldnames):
        raise UpstreamError(f"Stooq 没有返回 {symbol} 的 CSV 行情")

    bars: list[RawBar] = []
    for row in reader:
        day = _day(row.get("Date"))
        if day is None:
            continue
        open_time = datetime.combine(day, _SESSION_ANCHOR_UTC, tzinfo=UTC)
        if open_time < start or open_time >= end:
            continue
        close = _decimal(row.get("Close"))
        if close is None:
            # 没有收盘价的行不是一根 K 线：补 0 会写出一个不存在的价格。
            continue
        opens = _decimal(row.get("Open"))
        highs = _decimal(row.get("High"))
        lows = _decimal(row.get("Low"))
        volume = _decimal(row.get("Volume"))
        bars.append(
            RawBar(
                symbol=symbol,
                open_time=open_time,
                # 缺列才退回收盘价；上游真实的 0（`Decimal("0")` 是假值）不能被顶掉。
                open=close if opens is None else opens,
                high=close if highs is None else highs,
                low=close if lows is None else lows,
                close=close,
                # 成交量缺失按 0 记：缺量不等于没有价格，不该因此丢掉整根 K 线。
                volume=Decimal(0) if volume is None else volume,
            )
        )
    return bars

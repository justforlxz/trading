"""Yahoo chart API：分钟级 K 线，免费源是延迟行情。

`GET {url}` 的 `{symbol}` 由标的名替换；查询串固定为「1 分钟级、最近一个交易日」。
返回体是 `chart.result[0]` 里的并列数组：`timestamp[]` 与
`indicators.quote[0].{open,high,low,close,volume}[]`，按索引一一对应。

只交出**已收盘**的 K 线：最后一根正在形成的分钟也在上游的返回里，它的收盘价还会变，
写进 `candles`（该表只收已收盘 K 线）就是伪造历史。

**本模块没有任何定时原语**：什么时候抓由 `app/jobs/market_data.py` 的调度器决定。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx

from app.core import UpstreamError
from app.exchange.providers.http import get_text
from app.exchange.providers.raw import RawBar
from app.shared import bar_seconds

__all__ = ["YahooSource", "parse_yahoo"]


def _url_for(options: Mapping[str, Any], symbol: str) -> str:
    template = options.get("url")
    template = template.strip() if isinstance(template, str) else ""
    if not template:
        raise UpstreamError("Yahoo 行情源未配置上游地址")
    return template.replace("{symbol}", symbol)


#: 价格的小数位：Yahoo 的列是二进制浮点（`608.450012207031`），按它入库会把浮点
#: 尾巴带到库和首页。美股最小报价单位是美分，不足 1 美元的标的按 4 位小数报价，
#: 因此 4 位小数既不会丢掉真实精度，也不会留下 `...00012207031`。
_PRICE_QUANTUM = Decimal("0.0001")
#: 成交量是股数，取整；上游给浮点时不要小数尾巴。
_VOLUME_QUANTUM = Decimal("1")


def _decimal(value: Any, quantum: Decimal = _PRICE_QUANTUM) -> Decimal | None:
    """上游价格 → `Decimal`；缺值给 `None`，不用 0 冒充一个不存在的价格。"""

    if value is None:
        return None
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def _at(column: Any, index: int) -> Any:
    """并列数组按索引取值；上游某列短了按缺值处理，不错位。"""

    if not isinstance(column, list) or index >= len(column):
        return None
    return column[index]


def _load_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise UpstreamError(f"Yahoo 行情上游返回的不是 JSON: {exc}") from exc


class YahooSource:
    """Yahoo chart API：1 分钟 K 线。免费源延迟 15 分钟级，`delayed=True`。"""

    name = "yahoo"
    bar = "1m"
    #: 免费源是延迟行情，不是实时报价。
    delayed = True

    def __init__(self, *, options: Mapping[str, Any], client: httpx.Client | None = None) -> None:
        self._options = options
        self._client = client

    def supports(self, symbols: Sequence[str]) -> bool:
        """Yahoo 按代码取数，任何美股代码都能试；代码本身不合法时上游会回错。"""

        return all(item.strip() for item in symbols)

    def url_for(self, symbol: str) -> str:
        """该标的的真实请求地址；接口显示来源链接时用它，保证与实际请求一致。"""

        return _url_for(self._options, symbol)

    def fetch(self, symbols: Sequence[str], start: datetime, end: datetime) -> list[RawBar]:
        bars: list[RawBar] = []
        for symbol in symbols:
            url = _url_for(self._options, symbol)
            bars.extend(
                parse_yahoo(_load_json(get_text(url, self._client)), symbol, start=start, end=end)
            )
        return bars


def parse_yahoo(payload: Any, symbol: str, *, start: datetime, end: datetime) -> list[RawBar]:
    """Yahoo chart JSON → 窗口内已收盘的 K 线；时间戳按 UTC 折成时刻。"""

    chart = payload.get("chart") if isinstance(payload, dict) else None
    if not isinstance(chart, dict):
        raise UpstreamError("Yahoo 返回内容缺少 chart 字段")
    if chart.get("error"):
        raise UpstreamError(f"Yahoo 返回错误: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise UpstreamError(f"Yahoo 没有返回 {symbol} 的行情")
    result = results[0] if isinstance(results[0], dict) else {}
    stamps = result.get("timestamp") or []
    quotes = (result.get("indicators") or {}).get("quote") or []
    columns = quotes[0] if quotes else {}
    if not isinstance(columns, dict):
        raise UpstreamError(f"Yahoo 返回的 {symbol} 缺少 quote 数组")

    opens = columns.get("open") or []
    highs = columns.get("high") or []
    lows = columns.get("low") or []
    closes = columns.get("close") or []
    volumes = columns.get("volume") or []

    # 一根 K 线在它的 open_time + 周期之后才算收盘。
    closed_before = end.timestamp() - bar_seconds(YahooSource.bar)
    bars: list[RawBar] = []
    for index, stamp in enumerate(stamps):
        if int(stamp) > closed_before:
            continue  # 还在形成中的那一根
        open_time = datetime.fromtimestamp(int(stamp), tz=UTC)
        if open_time < start or open_time >= end:
            continue
        prices = (
            _decimal(_at(opens, index)),
            _decimal(_at(highs, index)),
            _decimal(_at(lows, index)),
            _decimal(_at(closes, index)),
        )
        if any(item is None for item in prices):
            # 四个价格缺一个就不是一根可用的 K 线：补 0 会写出一个不存在的价格。
            continue
        volume = _decimal(_at(volumes, index), _VOLUME_QUANTUM)
        bars.append(
            RawBar(
                symbol=symbol,
                open_time=open_time,
                open=prices[0],
                high=prices[1],
                low=prices[2],
                close=prices[3],
                # 缺量不等于没有价格：成交量缺失按 0 记，不丢整根。
                volume=Decimal(0) if volume is None else volume,
            )
        )
    return bars

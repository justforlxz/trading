"""把上游取数实现包成 `BarProvider`：补周期、按市场规则定界、填来源名。

上游只给「标的 + 时刻 + OHLCV」，`candles` 要的是**规范定界的 K 线**：日线的
`open_time` 是该交易日正常时段开盘（`app.market.session.daily_open_time`），分钟级按
步长对齐（`floor_open_time`）。这两条规则属于行情域，取数实现（`app.exchange`）不碰，
因此由本层做一次映射。

来源名（`Bar.source`）写进 `candles` 主键，必须等于配置里的 provider 名：不知道从哪个
源来的价格不能当行情用。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import httpx

from app.core import Bar, BarProvider, Timeframe
from app.exchange import (
    build_source,
    source_bar,
    source_delayed,
    source_names,
    source_template,
    source_url,
)
from app.market import US_EQUITY, daily_open_time, floor_open_time

__all__ = [
    "build_provider",
    "provider_bar",
    "provider_delayed",
    "provider_names",
    "provider_template",
    "provider_url",
]


class _AlignedProvider:
    """一个上游实现 + 行情域的定界规则；对调用方只暴露 `BarProvider`。"""

    def __init__(self, *, name: str, source: Any) -> None:
        self.name = name
        self.bar = source_bar(name)
        self.delayed = source_delayed(name)
        self._source = source

    def supports(self, symbols: Sequence[str]) -> bool:
        return bool(self._source.supports(symbols))

    def fetch(self, symbols: Sequence[str], start: datetime, end: datetime) -> list[Bar]:
        timeframe = Timeframe.parse(self.bar)
        return [
            Bar(
                inst_id=raw.symbol,
                timeframe=timeframe,
                open_time=self._aligned(raw.open_time),
                open=raw.open,
                high=raw.high,
                low=raw.low,
                close=raw.close,
                volume=raw.volume,
                confirm=True,
                source=self.name,
            )
            for raw in self._source.fetch(symbols, start, end)
        ]

    def _aligned(self, open_time: datetime) -> datetime:
        """上游时刻 → 该周期的规范 `open_time`（日线按美股交易日开盘定界）。"""

        if self.bar == "1d":
            return daily_open_time(US_EQUITY, open_time)
        return floor_open_time(open_time, self.bar, US_EQUITY)


def build_provider(
    name: str,
    *,
    options: Mapping[str, Any],
    client: httpx.Client | None = None,
) -> BarProvider:
    """按名字构造 provider；名字未登记时 `app.core.get` 抛参数不合法。"""

    return _AlignedProvider(name=name, source=build_source(name, options=options, client=client))


def provider_names() -> list[str]:
    """已登记的 provider 名；配置校验用它列出可选值。"""

    return source_names()


def provider_bar(name: str) -> str:
    """该实现实际提供的周期（`1m` / `1d`）。"""

    return source_bar(name)


def provider_delayed(name: str) -> bool:
    """该来源是否是延迟行情；未登记的来源按延迟处理，绝不当作实时。"""

    return source_delayed(name)


def provider_template(name: str) -> str | None:
    """该来源的上游地址模板（含 `{symbol}`）；配置把它交给 provider 拼实际请求。"""

    return source_template(name)


def provider_url(name: str, symbol: str) -> str | None:
    """某个标的在该来源下的真实地址；接口把它作为「来源」链接返回。

    必须用实现自己的地址构造：直接返回模板会让首页出现一个带花括号、点开 404 的链接。
    """

    return source_url(name, symbol)

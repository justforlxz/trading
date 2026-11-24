"""把上游取数实现包成 `BarProvider`：补周期、按市场规则定界、填来源名。

一个实现可以提供多个周期（Yahoo 同时给分钟级与日线），因此 `build_provider` 要指定
这一次要哪个周期：定界规则（日线按美股交易日开盘、分钟级按步长对齐）与上游地址都跟
周期绑定，不能只凭 provider 名猜。

**「这根 K 线是否已定稿」也在这里判断**：取数层不认识交易时段，它把上游返回的每一根
都交上来；分钟级看这一分钟是否走完，日线看当天收盘（美东 16:00）。少了这一步，正在
形成的日线会在盘中就被当成收盘价写进 `candles`。

上游只给「标的 + 时刻 + OHLCV」，`candles` 要的是**规范定界的 K 线**：日线的
`open_time` 是该交易日正常时段开盘（`app.market.session.daily_open_time`），分钟级按
步长对齐（`floor_open_time`）。这两条规则属于行情域，取数实现（`app.exchange`）不碰，
因此由本层做一次映射。

来源名（`Bar.source`）写进 `candles` 主键，必须等于配置里的 provider 名：不知道从哪个
源来的价格不能当行情用。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.core import Bar, BarProvider, Timeframe
from app.exchange import (
    build_source,
    source_bars,
    source_delayed,
    source_names,
    source_template,
    source_url,
)
from app.market import (
    US_EQUITY,
    daily_open_time,
    floor_open_time,
    from_epoch,
    settlement_epoch,
    trading_day_of,
)
from app.shared import bar_seconds

__all__ = [
    "build_provider",
    "provider_bars",
    "provider_delayed",
    "provider_names",
    "provider_template",
    "provider_url",
]


class _AlignedProvider:
    """一个上游实现 + 一个周期 + 行情域的定界规则；对调用方只暴露 `BarProvider`。"""

    def __init__(self, *, name: str, bar: str, source: Any) -> None:
        self.name = name
        self.bar = bar
        self.delayed = source_delayed(name)
        self._source = source

    def supports(self, symbols: Sequence[str]) -> bool:
        return bool(self._source.supports(symbols))

    def fetch(self, symbols: Sequence[str], start: datetime, end: datetime) -> list[Bar]:
        timeframe = Timeframe.parse(self.bar)
        bars = [
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
        return [bar for bar in bars if self._finished(bar, end)]

    def _finished(self, bar: Bar, end: datetime) -> bool:
        """`end` 之前这根 K 线是否已经定稿；未定稿的价格还会变，不能当历史写库。

        分钟级：`open_time + 周期` 走完才算；日线：该交易日收盘（美东 16:00）才算——
        用「开盘 + 24 小时」会把日线拖到次日同一时刻，等于晚一天才落库。
        """

        if self.bar == "1d":
            return from_epoch(settlement_epoch(trading_day_of(bar.open_time))) <= end
        return bar.open_time + timedelta(seconds=bar_seconds(self.bar)) <= end

    def _aligned(self, open_time: datetime) -> datetime:
        """上游时刻 → 该周期的规范 `open_time`（日线按美股交易日开盘定界）。"""

        if self.bar == "1d":
            return daily_open_time(US_EQUITY, open_time)
        return floor_open_time(open_time, self.bar, US_EQUITY)


def build_provider(
    name: str,
    *,
    bar: str = "",
    options: Mapping[str, Any],
    client: httpx.Client | None = None,
) -> BarProvider:
    """按名字与周期构造 provider；名字未登记时 `app.core.get` 抛参数不合法。"""

    wanted = bar or provider_bars(name)[0]
    return _AlignedProvider(
        name=name,
        bar=wanted,
        source=build_source(name, options=options, client=client),
    )


def provider_names() -> list[str]:
    """已登记的 provider 名；配置校验用它列出可选值。"""

    return source_names()


def provider_bars(name: str) -> tuple[str, ...]:
    """该实现实际提供的周期，按展示优先级排列（第一个是首页读数用的周期）。"""

    return source_bars(name)


def provider_delayed(name: str) -> bool:
    """该来源是否是延迟行情；未登记的来源按延迟处理，绝不当作实时。"""

    return source_delayed(name)


def provider_template(name: str, bar: str = "") -> str | None:
    """该来源某个周期的上游地址模板（含 `{symbol}`）；配置把它交给 provider 拼请求。"""

    return source_template(name, bar)


def provider_url(name: str, symbol: str, bar: str = "") -> str | None:
    """某个标的在该来源下的真实地址；接口把它作为「来源」链接返回。

    必须用实现自己的地址构造：直接返回模板会让首页出现一个带花括号、点开 404 的链接。
    """

    return source_url(name, symbol, bar)

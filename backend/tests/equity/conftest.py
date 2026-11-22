"""美股行情用例的公共装配：假 provider、固定时刻与落库辅助。

替身只实现 `BarProvider` 的签名（`name` / `bar` / `supports` / `fetch`），记录每次
`fetch` 的入参；真实上游的解析由 `tests/exchange/test_equity_providers.py` 覆盖。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select

from app.core import Bar, Timeframe, UpstreamError
from app.db import session_scope
from app.market import Candle, upsert_candles

#: 美东 2026-11-20（周五）15:59，即正常时段的最后一分钟。
LAST_MINUTE_ET = datetime(2026, 11, 20, 20, 59, tzinfo=UTC)
#: 同一交易日的收盘时刻。
CLOSE_ET = datetime(2026, 11, 20, 21, 0, tzinfo=UTC)


class FakeProvider:
    """可控的上游：返回预设 K 线，记录每次 `fetch` 的入参与 provider 名。"""

    def __init__(
        self,
        name: str,
        *,
        bar: str = "1m",
        bars: Sequence[Bar] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.bar = bar
        self.bars = list(bars or [])
        self.error = error
        self.calls: list[tuple[tuple[str, ...], datetime, datetime]] = []

    def supports(self, symbols: Sequence[str]) -> bool:
        return all(item.strip() for item in symbols)

    def fetch(self, symbols: Sequence[str], start: datetime, end: datetime) -> list[Bar]:
        self.calls.append((tuple(symbols), start, end))
        if self.error is not None:
            raise self.error
        wanted = set(symbols)
        return [
            Bar(
                inst_id=bar.inst_id,
                timeframe=bar.timeframe,
                open_time=bar.open_time,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                confirm=True,
                source=self.name,
            )
            for bar in self.bars
            if bar.inst_id in wanted
        ]


def equity_bar(
    symbol: str = "SPY",
    *,
    open_time: datetime = LAST_MINUTE_ET,
    bar: str = "1m",
    close: str = "689.81",
    source: str = "yahoo",
    market_session: str = "",
) -> Bar:
    """一根 K 线；价格用固定值，断言不必容忍浮点误差。"""

    return Bar(
        inst_id=symbol,
        timeframe=Timeframe.parse(bar),
        open_time=open_time,
        open=Decimal("688.00"),
        high=Decimal("690.00"),
        low=Decimal("687.50"),
        close=Decimal(close),
        volume=Decimal("1000"),
        confirm=True,
        source=source,
        market_session=market_session,
    )


def seed(*bars: Bar) -> None:
    """直接落库，绕过 provider：用于只读路径与概览口径的用例。"""

    upsert_candles(bars)


def candle_count(*, symbol: str | None = None) -> int:
    """库内 K 线行数；`symbol` 为空时统计全表。"""

    statement = select(func.count()).select_from(Candle)
    if symbol is not None:
        statement = statement.where(Candle.symbol == symbol)
    with session_scope() as session:
        return int(session.scalar(statement) or 0)


def failing_provider(error: Exception) -> FakeProvider:
    """一次必定失败的上游；用来验证退避与健康降级。"""

    return FakeProvider("yahoo", error=error)


def upstream_error(message: str = "连接被拒绝") -> UpstreamError:
    return UpstreamError(message)

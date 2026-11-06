"""Yahoo Finance chart v8 适配器（免 key，无 SLA）。

实测（2026-11-06）：`v8/finance/chart` 需要常规 User-Agent，`v7/quote` 返回 401。
该源只用于「真实美股基准价 / 关系分析 / 时段交叉校验」，**不是交易价格来源**。
失败一律抛 `EquitySourceUnavailable`，由上层写 `MISSING_SOURCE`，绝不拿 OKX 指数冒充收盘价。
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.adapters.equity.base import EquitySourceUnavailable, EquitySymbolNotFound
from app.market.core.calendar import session_phase
from app.ports.market_data import EquityCandleRow, EquityQuote

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) trading-backend/0.1"


# Yahoo 返回的是 float32 精度（如 344.1700134277344），落库前量化到 1e-4，
# 去掉浮点尾数，同时不引入任何价格修正。
PRICE_QUANT = Decimal("0.0001")


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(PRICE_QUANT)


class YahooEquitySource:
    """`EquitySource` 的 Yahoo 实现。"""

    name = "yahoo"

    def __init__(
        self,
        timeout_seconds: float = 10.0,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            transport=transport,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "YahooEquitySource":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def _chart(self, symbol: str, *, range_: str, interval: str) -> dict[str, Any]:
        try:
            response = await self._client.get(
                CHART_URL.format(symbol=symbol),
                params={"range": range_, "interval": interval, "includePrePost": "false"},
            )
        except httpx.HTTPError as exc:
            raise EquitySourceUnavailable(f"yahoo request failed: {exc}") from exc

        if response.status_code in (401, 403, 404):
            raise EquitySymbolNotFound(f"yahoo symbol unavailable: {symbol}")
        if response.status_code >= 400:
            raise EquitySourceUnavailable(f"yahoo http {response.status_code} for {symbol}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise EquitySourceUnavailable("yahoo returned non-json body") from exc

        chart = payload.get("chart") or {}
        if chart.get("error"):
            raise EquitySourceUnavailable(f"yahoo chart error: {chart['error']}")
        results = chart.get("result") or []
        if not results:
            raise EquitySourceUnavailable(f"yahoo returned no result for {symbol}")
        return results[0]

    async def fetch_daily(self, symbol: str, lookback_days: int = 10) -> list[EquityCandleRow]:
        chart = await self._chart(symbol, range_=f"{max(lookback_days, 1)}d", interval="1d")
        return self._parse_candles(chart, symbol, interval="1d", session="REGULAR")

    async def fetch_minutes(
        self, symbol: str, range_: str = "5d", interval: str = "5m"
    ) -> list[EquityCandleRow]:
        """分钟线（含盘前/盘后标注），用于与 OKX 时段做交叉校验。"""

        chart = await self._chart(symbol, range_=range_, interval=interval)
        return self._parse_candles(chart, symbol, interval=interval, session=None)

    async def fetch_quote(self, symbol: str) -> EquityQuote | None:
        chart = await self._chart(symbol, range_="1d", interval="1m")
        meta = chart.get("meta") or {}
        price = _to_decimal(meta.get("regularMarketPrice"))
        if price is None:
            return None
        ts = meta.get("regularMarketTime")
        when = datetime.fromtimestamp(int(ts), tz=UTC) if ts else datetime.now(tz=UTC)
        return EquityQuote(symbol=symbol, price=price, ts=when, source=self.name)

    @staticmethod
    def _parse_candles(
        chart: dict[str, Any],
        symbol: str,
        *,
        interval: str,
        session: str | None,
    ) -> list[EquityCandleRow]:
        timestamps = chart.get("timestamp") or []
        quotes = (chart.get("indicators") or {}).get("quote") or [{}]
        quote = quotes[0]
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []

        rows: list[EquityCandleRow] = []
        for index, ts in enumerate(timestamps):
            try:
                open_ = _to_decimal(opens[index])
                high = _to_decimal(highs[index])
                low = _to_decimal(lows[index])
                close = _to_decimal(closes[index])
            except IndexError:
                continue
            if None in (open_, high, low, close):
                continue
            when = datetime.fromtimestamp(int(ts), tz=UTC)
            rows.append(
                EquityCandleRow(
                    symbol=symbol,
                    interval=interval,
                    ts=when,
                    open=open_,  # type: ignore[arg-type]
                    high=high,  # type: ignore[arg-type]
                    low=low,  # type: ignore[arg-type]
                    close=close,  # type: ignore[arg-type]
                    volume=_to_decimal(volumes[index] if index < len(volumes) else 0)
                    or Decimal("0"),
                    session=session or session_phase(when),
                    source=YahooEquitySource.name,
                )
            )
        return rows

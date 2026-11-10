"""OKX 公开行情接口 → `MarketDataPort` 实现。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.exchange.errors import ExchangeError
from app.exchange.okx.bars import from_okx_bar, to_okx_bar
from app.exchange.okx.client import OkxClient
from app.exchange.okx.instruments import parse_instruments
from app.exchange.ports import Candle, InstrumentInfo, Ticker, utc_from_millis

__all__ = ["MAX_CANDLE_LIMIT", "OkxMarketData"]

# 上游单次请求的 K 线上限。
MAX_CANDLE_LIMIT = 100

_INSTRUMENTS_PATH = "/api/v5/public/instruments"
_CANDLES_PATH = "/api/v5/market/candles"
_HISTORY_CANDLES_PATH = "/api/v5/market/history-candles"
_TICKER_PATH = "/api/v5/market/ticker"

# 本节点的行情范围是现货；合约与衍生品属于后续阶段。
_SPOT = "SPOT"

_SOURCE = "okx"


class OkxMarketData:
    """基于 OKX 公开 REST 的行情端口实现。

    K 线统一按 `open_time` 升序返回（上游是倒序），`bar` 统一是内部规范写法。
    """

    def __init__(self, client: OkxClient, *, source: str = _SOURCE) -> None:
        self._client = client
        self._source = source

    def instruments(self) -> list[InstrumentInfo]:
        """拉取全部现货标的元数据。"""

        rows = self._client.get(_INSTRUMENTS_PATH, {"instType": _SPOT})
        return parse_instruments(rows)

    def candles(self, inst_id: str, bar: str, *, limit: int = MAX_CANDLE_LIMIT) -> list[Candle]:
        """拉取最近 `limit` 根 K 线。"""

        return self._candles(_CANDLES_PATH, inst_id, bar, limit=limit)

    def history_candles(
        self,
        inst_id: str,
        bar: str,
        *,
        after: datetime | None = None,
        limit: int = MAX_CANDLE_LIMIT,
    ) -> list[Candle]:
        """拉取历史 K 线；`after` 指向更早的一段（不含该时刻本身）。"""

        return self._candles(_HISTORY_CANDLES_PATH, inst_id, bar, limit=limit, after=after)

    def ticker(self, inst_id: str) -> Ticker:
        """拉取最新行情快照。"""

        rows = self._client.get(_TICKER_PATH, {"instId": inst_id})
        if not rows:
            raise ExchangeError(f"行情快照为空:{inst_id}")
        return _parse_ticker(rows[0])

    def close(self) -> None:
        """释放底层连接。"""

        self._client.close()

    def _candles(
        self,
        path: str,
        inst_id: str,
        bar: str,
        *,
        limit: int,
        after: datetime | None = None,
    ) -> list[Candle]:
        if not 1 <= limit <= MAX_CANDLE_LIMIT:
            raise ValueError(f"limit 必须在 1..{MAX_CANDLE_LIMIT} 之间")
        okx_bar = to_okx_bar(bar)
        params: dict[str, Any] = {"instId": inst_id, "bar": okx_bar, "limit": str(limit)}
        if after is not None:
            if after.tzinfo is None:
                raise ValueError("after 必须是带时区的时间")
            params["after"] = str(round(after.timestamp() * 1000))
        rows = self._client.get(path, params)
        canonical_bar = from_okx_bar(okx_bar)
        return [_parse_candle(row, inst_id, canonical_bar, self._source) for row in reversed(rows)]


def _parse_candle(row: Any, inst_id: str, bar: str, source: str) -> Candle:
    """上游行格式：`[ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]`。"""

    if not isinstance(row, list) or len(row) < 9:
        raise ExchangeError(f"K 线数据结构异常:{row!r}")
    try:
        return Candle(
            inst_id=inst_id,
            bar=bar,
            open_time=utc_from_millis(row[0]),
            open=Decimal(str(row[1])),
            high=Decimal(str(row[2])),
            low=Decimal(str(row[3])),
            close=Decimal(str(row[4])),
            volume=Decimal(str(row[5])),
            confirm=str(row[8]) == "1",
            source=source,
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ExchangeError(f"K 线数据非法:{row!r}") from exc


def _parse_ticker(row: Any) -> Ticker:
    if not isinstance(row, dict):
        raise ExchangeError("行情快照结构异常")
    try:
        return Ticker(
            inst_id=str(row["instId"]),
            last=Decimal(str(row["last"])),
            bid=Decimal(str(row["bidPx"])),
            ask=Decimal(str(row["askPx"])),
            volume_24h=Decimal(str(row["vol24h"])),
            ts=utc_from_millis(row["ts"]),
        )
    except KeyError as exc:
        raise ExchangeError(f"行情快照缺少字段:{exc}") from exc
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ExchangeError(f"行情快照数据非法:{row!r}") from exc

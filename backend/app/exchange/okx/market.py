"""OKX 公开行情接口 → `MarketDataPort` 实现。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core import (
    Bar,
    InstrumentRef,
    MarketDataPort,
    Ticker,
    Timeframe,
    ValidationError,
    utc_from_millis,
)
from app.exchange.errors import ExchangeError
from app.exchange.okx.bars import to_okx_bar
from app.exchange.okx.client import OkxClient
from app.exchange.okx.instruments import parse_instruments

__all__ = ["MAX_CANDLE_LIMIT", "OkxMarketData"]

# 上游单次请求的 K 线上限。
MAX_CANDLE_LIMIT = 100

_INSTRUMENTS_PATH = "/api/v5/public/instruments"
_CANDLES_PATH = "/api/v5/market/candles"
_HISTORY_CANDLES_PATH = "/api/v5/market/history-candles"
_TICKER_PATH = "/api/v5/market/ticker"

# 类别 → (落库来源标识, K 线成交量列, Ticker 24 小时成交量字段)。
#
# 行情按类别分开取：同一产品的现货与永续各有一行行情，来源标识必须能区分，
# 否则混合行情没法按来源取数。
#
# 成交量口径全仓统一为标的币数量：现货的 `vol` / `vol24h` 就是币数，永续的
# `volCcy` / `volCcy24h` 才是币数（永续的 `vol` / `vol24h` 是张数）。取错列会
# 立刻污染 VWAP 与量能指标，而且落库后无法再用字段区分。
_PROFILE: dict[str, tuple[str, int, str]] = {
    "SPOT": ("okx_spot", 5, "vol24h"),
    "SWAP": ("okx_swap", 6, "volCcy24h"),
}


def _normalize_inst_type(inst_type: str) -> str:
    """规范类别写法；未知类别直接报错，不悄悄退回现货列。"""

    key = inst_type.strip().upper()
    if key not in _PROFILE:
        supported = ", ".join(_PROFILE)
        raise ValidationError(f"不支持的标的类别 {inst_type!r}; 支持: {supported}")
    return key


class OkxMarketData(MarketDataPort):
    """基于 OKX 公开 REST 的行情端口实现。

    K 线统一按 `open_time` 升序返回（上游是倒序）。周期在上游是 `1H`/`1D` 这类
    写法，进出本类一律是规范 `Timeframe`，映射只发生在 `okx.bars`。

    类别一律由调用方按 `inst_type` 给出：上游标的与 K 线接口一次只服务一类，
    适配层不从 `inst_id` 拆字符串推断。
    """

    def __init__(self, client: OkxClient) -> None:
        self._client = client

    def instruments(self, inst_type: str) -> list[InstrumentRef]:
        """拉取某一类别的全部标的元数据。"""

        params = {"instType": _normalize_inst_type(inst_type)}
        rows = self._client.get(_INSTRUMENTS_PATH, params)
        return parse_instruments(rows)

    def candles(
        self,
        inst_id: str,
        timeframe: Timeframe,
        *,
        inst_type: str,
        limit: int = MAX_CANDLE_LIMIT,
    ) -> list[Bar]:
        """拉取最近 `limit` 根 K 线；`inst_type` 决定成交量取哪一列。"""

        return self._candles(_CANDLES_PATH, inst_id, timeframe, inst_type=inst_type, limit=limit)

    def history_candles(
        self,
        inst_id: str,
        timeframe: Timeframe,
        *,
        inst_type: str,
        after: datetime | None = None,
        limit: int = MAX_CANDLE_LIMIT,
    ) -> list[Bar]:
        """拉取历史 K 线；`after` 指向更早的一段（不含该时刻本身）。"""

        return self._candles(
            _HISTORY_CANDLES_PATH,
            inst_id,
            timeframe,
            inst_type=inst_type,
            limit=limit,
            after=after,
        )

    def ticker(self, inst_id: str, *, inst_type: str) -> Ticker:
        """拉取最新行情快照；`inst_type` 决定 24 小时成交量取哪个字段。"""

        _, _, volume_field = _PROFILE[_normalize_inst_type(inst_type)]
        rows = self._client.get(_TICKER_PATH, {"instId": inst_id})
        if not rows:
            raise ExchangeError(f"行情快照为空:{inst_id}")
        return _parse_ticker(rows[0], volume_field=volume_field)

    def close(self) -> None:
        """释放底层连接。"""

        self._client.close()

    def _candles(
        self,
        path: str,
        inst_id: str,
        timeframe: Timeframe,
        *,
        inst_type: str,
        limit: int,
        after: datetime | None = None,
    ) -> list[Bar]:
        if not 1 <= limit <= MAX_CANDLE_LIMIT:
            raise ValueError(f"limit 必须在 1..{MAX_CANDLE_LIMIT} 之间")
        source, volume_index, _ = _PROFILE[_normalize_inst_type(inst_type)]
        params: dict[str, Any] = {
            "instId": inst_id,
            "bar": to_okx_bar(timeframe.value),
            "limit": str(limit),
        }
        if after is not None:
            if after.tzinfo is None:
                raise ValueError("after 必须是带时区的时间")
            params["after"] = str(round(after.timestamp() * 1000))
        rows = self._client.get(path, params)
        return [
            _parse_candle(row, inst_id, timeframe, source=source, volume_index=volume_index)
            for row in reversed(rows)
        ]


def _parse_candle(
    row: Any, inst_id: str, timeframe: Timeframe, *, source: str, volume_index: int
) -> Bar:
    """上游行格式：`[ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]`。"""

    if not isinstance(row, list) or len(row) < 9:
        raise ExchangeError(f"K 线数据结构异常:{row!r}")
    try:
        return Bar(
            inst_id=inst_id,
            timeframe=timeframe,
            open_time=utc_from_millis(row[0]),
            open=Decimal(str(row[1])),
            high=Decimal(str(row[2])),
            low=Decimal(str(row[3])),
            close=Decimal(str(row[4])),
            volume=Decimal(str(row[volume_index])),
            confirm=str(row[8]) == "1",
            source=source,
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ExchangeError(f"K 线数据非法:{row!r}") from exc


def _parse_ticker(row: Any, *, volume_field: str) -> Ticker:
    if not isinstance(row, dict):
        raise ExchangeError("行情快照结构异常")
    try:
        return Ticker(
            inst_id=str(row["instId"]),
            last=Decimal(str(row["last"])),
            bid=Decimal(str(row["bidPx"])),
            ask=Decimal(str(row["askPx"])),
            volume_24h=Decimal(str(row[volume_field])),
            ts=utc_from_millis(row["ts"]),
        )
    except KeyError as exc:
        raise ExchangeError(f"行情快照缺少字段:{exc}") from exc
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ExchangeError(f"行情快照数据非法:{row!r}") from exc

"""OKX K 线适配器：增量采集（candles）与游标回补（history-candles）。

上游两种返回顺序（candles/history-candles 均为**时间倒序**）在这里统一翻成升序，
业务层只面对「按 open_time 升序、去重后」的序列。
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.adapters.okx.bars import to_okx_bar
from app.adapters.okx.client import OkxClient
from app.market.core.bars import bar_seconds, normalize_bar
from app.ports.market_data import CandleRow

CANDLES_PATH = "/api/v5/market/candles"
HISTORY_PATH = "/api/v5/market/history-candles"
MAX_LIMIT = 300
HISTORY_MAX_LIMIT = 100


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else Decimal("0")


def _ms_to_datetime(value: Any) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def parse_candle(item: list[Any], inst_id: str, bar: str, source: str) -> CandleRow:
    """OKX K 线数组 → DTO。

    字段顺序：`[ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]`。
    """

    confirm = item[8] if len(item) > 8 else "1"
    return CandleRow(
        inst_id=inst_id,
        bar=normalize_bar(bar),
        open_time=_ms_to_datetime(item[0]),
        open=_decimal(item[1]),
        high=_decimal(item[2]),
        low=_decimal(item[3]),
        close=_decimal(item[4]),
        vol=_decimal(item[5]),
        vol_ccy=_decimal(item[6]),
        vol_ccy_quote=_decimal(item[7]) if len(item) > 7 else Decimal("0"),
        confirm=str(confirm) == "1",
        source=source,
    )


def parse_candles(data: list[list[Any]], inst_id: str, bar: str, source: str) -> list[CandleRow]:
    """解析并归一到升序去重序列。"""

    by_time: dict[datetime, CandleRow] = {}
    for item in data:
        row = parse_candle(item, inst_id, bar, source)
        by_time[row.open_time] = row
    return [by_time[key] for key in sorted(by_time)]


class OkxCandleSource:
    """`CandleSource` 的 OKX 实现。"""

    def __init__(self, client: OkxClient) -> None:
        self._client = client

    async def fetch_candles(
        self, inst_id: str, bar: str, limit: int = MAX_LIMIT
    ) -> list[CandleRow]:
        """最近 N 根（含最多一根未完成 bar）；`limit` 上限 300，超出直接报错。"""

        if limit > MAX_LIMIT:
            raise ValueError(f"limit must be <= {MAX_LIMIT}, got {limit}")
        params = {"instId": inst_id, "bar": to_okx_bar(bar), "limit": str(limit)}
        data = await self._client.get(CANDLES_PATH, params, limiter="candles")
        return parse_candles(data, inst_id, bar, "okx_rest")

    async def fetch_history(
        self,
        inst_id: str,
        bar: str,
        start: datetime,
        end: datetime,
        page_limit: int = 100,
    ) -> list[CandleRow]:
        """按 `after` 游标向前翻页，直到越过 start；返回 `[start, end)` 内升序数据。"""

        if end <= start:
            raise ValueError("end must be after start")
        okx_bar = to_okx_bar(bar)
        # history-candles 的 limit 上限是 100（与 candles 的 300 不同）。
        page_limit = min(page_limit, HISTORY_MAX_LIMIT)
        step_ms = bar_seconds(bar) * 1000
        start_ms = int(start.timestamp() * 1000)
        cursor = int(end.timestamp() * 1000)
        collected: dict[datetime, CandleRow] = {}

        while True:
            params = {
                "instId": inst_id,
                "bar": okx_bar,
                "limit": str(page_limit),
                "after": str(cursor),
            }
            data = await self._client.get(HISTORY_PATH, params, limiter="history")
            if not data:
                break
            page = parse_candles(data, inst_id, bar, "okx_history")
            for row in page:
                collected[row.open_time] = row
            oldest_ms = int(page[0].open_time.timestamp() * 1000)
            if oldest_ms <= start_ms or oldest_ms <= 0:
                break
            # 防御：游标不前进时立即停止，避免无限翻页。
            cursor = oldest_ms - step_ms if oldest_ms >= cursor else oldest_ms
            if cursor <= start_ms:
                break

        return [collected[key] for key in sorted(collected) if start <= key < end]

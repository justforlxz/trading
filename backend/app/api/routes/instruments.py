"""标的域端点：搜索、详情与 K 线窗口。

搜索与详情只读标的表，K 线窗口只读已落库的蜡烛。详情里的「另一条腿」价格
取最新一根日线收盘价，两条腿都缺数据时不产出价差，不用 0 占位。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query

from app.api.mapping import decimal_str, instrument_info, instrument_ref
from app.api.schemas import Candle as CandlePayload
from app.api.schemas import (
    CandleSeriesResponse,
    InstrumentDetailResponse,
    InstrumentListResponse,
    InstrumentSearchResponse,
    SiblingQuote,
)
from app.api.schemas.common import Bar, DataSource, InstType
from app.instrument import Instrument, get_instrument_pair, list_instruments, list_tradable
from app.market import data_range, integrity, load_candles

__all__ = ["instruments_router"]

instruments_router = APIRouter(tags=["instruments"])

# 详情页的参考价 = 最新一根日线收盘价；只看最近一周，避免读出整段历史。
_LAST_CLOSE_BAR = "1d"
_LAST_CLOSE_LOOKBACK = timedelta(days=7)
_SPREAD_PLACES = Decimal("0.0001")


@instruments_router.get("/instruments/search")
def search_instruments(
    q: str = Query(..., min_length=1), inst_type: InstType | None = None
) -> InstrumentSearchResponse:
    """按代码或产品键做大小写不敏感的包含匹配，可按标的类型过滤。"""

    needle = q.strip().lower()
    if not needle:
        raise HTTPException(status_code=422, detail="搜索关键字不能为空")

    items = [
        instrument_ref(row)
        for row in list_instruments()
        if (inst_type is None or row.inst_type == inst_type)
        and (needle in row.symbol.lower() or needle in row.product_key.lower())
    ]
    return InstrumentSearchResponse(items=items)


@instruments_router.get("/instruments")
def list_tradable_instruments(inst_type: InstType = Query(...)) -> InstrumentListResponse:
    """某一类别的可交易标的（`state == live`），不按资产类别过滤。"""

    rows = list_tradable(inst_type)
    return InstrumentListResponse(items=[instrument_ref(row) for row in rows])


@instruments_router.get("/instruments/{inst_id}")
def get_instrument(inst_id: str) -> InstrumentDetailResponse:
    """单标的详情：交易参数 + 同产品的另一条腿（有行情时才有价差）。"""

    row = _require_instrument(inst_id)
    return InstrumentDetailResponse(
        instrument=instrument_info(row),
        siblings=_siblings(row),
    )


@instruments_router.get("/instruments/{inst_id}/candles")
def get_instrument_candles(
    inst_id: str,
    bar: Bar = Query(...),
    source: DataSource = Query(...),
    limit: int = Query(200, ge=1, le=1000),
) -> CandleSeriesResponse:
    """某一来源的已落库 K 线尾部窗口，附带该来源真实的可用区间与缺口标记。

    `source` 必填、没有默认值：同一标的可能同时存有 OKX 行情与美股代理行情，两者
    的日界不同（OKX 是 16:00 UTC，代理是美东 09:30），静默挑一个就把两种来源拼成
    一条时间轴（Q5 / D3）。缺参会由参数校验直接拒绝，不会默认成 OKX。
    """

    row = _require_instrument(inst_id)
    candles = load_candles(row.symbol, bar, source=source)[-limit:]
    available = data_range(row.symbol, bar, source=source)

    return CandleSeriesResponse(
        inst_id=row.symbol,
        bar=bar,
        data_source=source,
        available_from=None if available is None else available[0],
        available_to=None if available is None else available[1],
        has_gap=integrity(row.symbol, bar, source=source).missing > 0,
        candles=[
            CandlePayload(
                open_time=candle.open_time,
                open=decimal_str(candle.open),
                high=decimal_str(candle.high),
                low=decimal_str(candle.low),
                close=decimal_str(candle.close),
                volume=decimal_str(candle.volume),
                is_closed=candle.confirm,
                data_source=candle.source,
            )
            for candle in candles
        ],
    )


def _require_instrument(inst_id: str) -> Instrument:
    row = _find_instrument(inst_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"未找到标的 {inst_id}")
    return row


def _find_instrument(inst_id: str) -> Instrument | None:
    return next((row for row in list_instruments() if row.symbol == inst_id), None)


def _siblings(row: Instrument) -> list[SiblingQuote]:
    """同 product_key 的另一条腿；任一侧没有日线就不给价差。"""

    pair = get_instrument_pair(row.product_key)
    other = pair.counterpart(row)
    if other is None:
        return []

    own_close = _last_close(row.symbol)
    other_close = _last_close(other.symbol)
    if own_close is None or other_close is None or other_close == 0:
        return []

    spread = (own_close / other_close - Decimal(1)) * Decimal(100)
    return [
        SiblingQuote(
            inst_id=other.symbol,
            inst_type=other.inst_type,
            last_price=decimal_str(other_close),
            price_spread_pct=decimal_str(spread.quantize(_SPREAD_PLACES)),
        )
    ]


def _last_close(inst_id: str) -> Decimal | None:
    # 窗口起点必须落在整秒上：K 线时间轴以秒为粒度，亚秒部分会让读取直接报错。
    start = (datetime.now(UTC) - _LAST_CLOSE_LOOKBACK).replace(microsecond=0)
    candles = load_candles(inst_id, _LAST_CLOSE_BAR, start=start)
    return candles[-1].close if candles else None

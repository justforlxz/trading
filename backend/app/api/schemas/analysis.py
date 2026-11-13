"""标的详情聚合契约：报价、K 线、指标、关键价位、相关性与数据覆盖。"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import (
    Candle,
    DataSource,
    DecimalString,
    InstrumentInfo,
    UtcDatetime,
)

__all__ = [
    "AnalysisBar",
    "AnalysisCandles",
    "AnalysisCoverage",
    "AnalysisGap",
    "AnalysisIndicators",
    "AnalysisLevels",
    "AnalysisOverlay",
    "AnalysisOverlayPoint",
    "AnalysisPrice",
    "AnalysisQuote",
    "CorrelationReading",
    "InstrumentAnalysisResponse",
    "LinkedBacktest",
    "MomentumIndicators",
    "RelativeStrengthIndicators",
    "TrendIndicators",
    "VolatilityIndicators",
    "VolumeIndicators",
]

AnalysisBar = Literal["1d", "4h", "1h"]


class AnalysisPrice(BaseModel):
    """一种价格语义；`last` / `mark` / `index` 各自独立，缺失时整个对象为 null。"""

    price: DecimalString
    as_of: UtcDatetime
    source: DataSource
    change: DecimalString | None = None
    change_pct: DecimalString | None = None


class AnalysisQuote(BaseModel):
    last: AnalysisPrice | None = None
    mark: AnalysisPrice | None = None
    index: AnalysisPrice | None = None


class AnalysisOverlayPoint(BaseModel):
    time: UtcDatetime
    value: DecimalString


class AnalysisOverlay(BaseModel):
    name: str
    points: list[AnalysisOverlayPoint]


class AnalysisGap(BaseModel):
    start: UtcDatetime
    end: UtcDatetime
    missing: int


class AnalysisCandles(BaseModel):
    data_source: DataSource
    available_from: UtcDatetime | None = None
    available_to: UtcDatetime | None = None
    gaps: list[AnalysisGap]
    candles: list[Candle]
    overlays: list[AnalysisOverlay]


class TrendIndicators(BaseModel):
    close: DecimalString | None = None
    ma20: DecimalString | None = None
    ma60: DecimalString | None = None
    price_vs_ma20_pct: DecimalString | None = None
    price_vs_ma60_pct: DecimalString | None = None
    ma20_slope_pct: DecimalString | None = None
    ma60_slope_pct: DecimalString | None = None
    slope_window: int


class MomentumIndicators(BaseModel):
    rsi14: DecimalString | None = None
    macd: DecimalString | None = None
    macd_signal: DecimalString | None = None
    macd_hist: DecimalString | None = None


class VolatilityIndicators(BaseModel):
    atr14: DecimalString | None = None
    atr_pct: DecimalString | None = None
    atr_pct_avg20: DecimalString | None = None


class VolumeIndicators(BaseModel):
    current: DecimalString | None = None
    average20: DecimalString | None = None
    relative: DecimalString | None = None


class RelativeStrengthIndicators(BaseModel):
    benchmark_inst_id: str | None = None
    window: int
    symbol_return_pct: DecimalString | None = None
    benchmark_return_pct: DecimalString | None = None
    excess_return_pct: DecimalString | None = None


class AnalysisIndicators(BaseModel):
    trend: TrendIndicators
    momentum: MomentumIndicators
    volatility: VolatilityIndicators
    volume: VolumeIndicators
    relative_strength: RelativeStrengthIndicators
    readings: list[str]


class AnalysisLevels(BaseModel):
    window: int
    high20: DecimalString | None = None
    low20: DecimalString | None = None
    high_distance_pct: DecimalString | None = None
    low_distance_pct: DecimalString | None = None


class CorrelationReading(BaseModel):
    inst_id: str
    product_key: str
    role: Literal["benchmark", "related"]
    coefficient: DecimalString | None = None
    sample_size: int
    window: int
    window_start: UtcDatetime | None = None
    window_end: UtcDatetime | None = None


class LinkedBacktest(BaseModel):
    run_id: str
    strategy_instance_id: str
    strategy_name: str
    strategy_id: str
    data_source: DataSource
    total_return_pct: DecimalString
    max_drawdown_pct: DecimalString
    trade_count: int
    backtest_start_date: date
    backtest_end_date: date
    created_at: UtcDatetime


class AnalysisCoverage(BaseModel):
    bar: AnalysisBar
    data_source: DataSource
    available: bool
    unavailable_reason: str | None = None
    available_from: UtcDatetime | None = None
    available_to: UtcDatetime | None = None
    candle_count: int
    gap_count: int
    last_synced_at: UtcDatetime | None = None


_EXAMPLE_INSTRUMENT = {
    "inst_id": "XAAPL-USDT",
    "inst_type": "SPOT",
    "product_key": "AAPL",
    "asset_type": "tokenized_equity",
    "base_currency": "XAAPL",
    "quote_currency": "USDT",
    "tick_size": "0.01",
    "lot_size": "0.001",
    "min_order_size": "0.001",
    "listing_time": "2026-07-01T00:00:00Z",
    "trading_status": "live",
    "max_leverage": None,
}

_EXAMPLE_CANDLE = {
    "open_time": "2026-11-12T16:00:00Z",
    "open": "229.80",
    "high": "232.10",
    "low": "229.44",
    "close": "231.42",
    "volume": "1520.335",
    "is_closed": True,
    "data_source": "okx_spot",
}

_EXAMPLE_ANALYSIS = {
    "instrument": _EXAMPLE_INSTRUMENT,
    "bar": "1d",
    "quote": {
        "last": {
            "price": "231.42",
            "as_of": "2026-11-13T16:00:00Z",
            "source": "okx_spot",
            "change": "2.84",
            "change_pct": "1.24",
        },
        "mark": None,
        "index": None,
    },
    "candles": {
        "data_source": "okx_spot",
        "available_from": "2023-05-01T16:00:00Z",
        "available_to": "2026-11-12T16:00:00Z",
        "gaps": [],
        "candles": [_EXAMPLE_CANDLE],
        "overlays": [
            {
                "name": "MA20",
                "points": [{"time": "2026-11-12T16:00:00Z", "value": "226.51"}],
            },
            {
                "name": "MA60",
                "points": [{"time": "2026-11-12T16:00:00Z", "value": "219.08"}],
            },
        ],
    },
    "indicators": {
        "trend": {
            "close": "231.42",
            "ma20": "226.51",
            "ma60": "219.08",
            "price_vs_ma20_pct": "2.17",
            "price_vs_ma60_pct": "5.63",
            "ma20_slope_pct": "1.42",
            "ma60_slope_pct": "0.86",
            "slope_window": 5,
        },
        "momentum": {
            "rsi14": "61.4",
            "macd": "1.28",
            "macd_signal": "0.94",
            "macd_hist": "0.34",
        },
        "volatility": {"atr14": "5.32", "atr_pct": "2.30", "atr_pct_avg20": "1.90"},
        "volume": {"current": "1520.335", "average20": "1151.78", "relative": "1.32"},
        "relative_strength": {
            "benchmark_inst_id": "XQQQ-USDT",
            "window": 20,
            "symbol_return_pct": "7.80",
            "benchmark_return_pct": "3.20",
            "excess_return_pct": "4.60",
        },
        "readings": [
            "收盘价 231.42，MA20 为 226.51，价格位于 MA20 上方 2.17%；MA20 的 5 根斜率是 1.42%。",
            "RSI(14) 为 61.40，MACD 为 1.2800，信号线为 0.9400，柱状值为 0.3400。",
            "当前成交量是 20 根均量的 1.32 倍，近 20 根相对 XQQQ-USDT 的超额收益为 4.60 个百分点。",
        ],
    },
    "levels": {
        "window": 20,
        "high20": "238.90",
        "low20": "214.10",
        "high_distance_pct": "3.23",
        "low_distance_pct": "-7.48",
    },
    "correlations": [
        {
            "inst_id": "XQQQ-USDT",
            "product_key": "QQQ",
            "role": "benchmark",
            "coefficient": "0.68",
            "sample_size": 60,
            "window": 60,
            "window_start": "2026-08-20T16:00:00Z",
            "window_end": "2026-11-12T16:00:00Z",
        }
    ],
    "linked_strategies": [
        {
            "run_id": "bt_0001",
            "strategy_instance_id": "si_0001",
            "strategy_name": "AAPL 趋势",
            "strategy_id": "ma_cross",
            "data_source": "okx_spot",
            "total_return_pct": "12.4055",
            "max_drawdown_pct": "6.12",
            "trade_count": 37,
            "backtest_start_date": "2026-10-01",
            "backtest_end_date": "2026-11-01",
            "created_at": "2026-11-10T01:20:00Z",
        }
    ],
    "coverage": [
        {
            "bar": "1d",
            "data_source": "okx_spot",
            "available": True,
            "unavailable_reason": None,
            "available_from": "2023-05-01T16:00:00Z",
            "available_to": "2026-11-12T16:00:00Z",
            "candle_count": 846,
            "gap_count": 0,
            "last_synced_at": "2026-11-13T01:00:00Z",
        },
        {
            "bar": "4h",
            "data_source": "okx_spot",
            "available": False,
            "unavailable_reason": "尚未同步",
            "available_from": None,
            "available_to": None,
            "candle_count": 0,
            "gap_count": 0,
            "last_synced_at": None,
        },
        {
            "bar": "1h",
            "data_source": "okx_spot",
            "available": False,
            "unavailable_reason": "尚未同步",
            "available_from": None,
            "available_to": None,
            "candle_count": 0,
            "gap_count": 0,
            "last_synced_at": None,
        },
    ],
}


class InstrumentAnalysisResponse(BaseModel):
    instrument: InstrumentInfo
    bar: AnalysisBar
    quote: AnalysisQuote
    candles: AnalysisCandles
    indicators: AnalysisIndicators
    levels: AnalysisLevels
    correlations: list[CorrelationReading]
    linked_strategies: list[LinkedBacktest]
    coverage: list[AnalysisCoverage]

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_ANALYSIS]})

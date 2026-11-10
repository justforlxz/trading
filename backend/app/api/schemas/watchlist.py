"""自选与标的详情契约：行情快照、K 线、相关标的、价格提醒。

所有响应模型带 `examples`，它们随 `contracts/openapi.json` 一起成为前端 MSW
fixture 的唯一来源；页面不得另造数据。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import (
    AlertDirection,
    AssetType,
    Bar,
    Candle,
    DataSource,
    DecimalString,
    InstrumentInfo,
    InstrumentRef,
    SiblingQuote,
    Signal,
    UtcDatetime,
)

__all__ = [
    "CandleSeriesResponse",
    "InstrumentDetailResponse",
    "InstrumentSearchResponse",
    "PriceAlert",
    "PriceAlertRequest",
    "RelatedInstrument",
    "RelatedInstrumentsResponse",
    "WatchlistAddRequest",
    "WatchlistItem",
    "WatchlistResponse",
    "WatchlistUpdateRequest",
]

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

_EXAMPLE_SIGNAL = {
    "signal_id": "sig_0001",
    "strategy_instance_id": "si_0001",
    "inst_id": "XAAPL-USDT",
    "inst_type": "SPOT",
    "action": "BUY",
    "bar": "1h",
    "price": "231.42",
    "reason": "MA20 上穿 MA60",
    "generated_at": "2026-11-10T07:00:00Z",
    "target_weight": "0.25",
}


_EXAMPLE_ALERT = {
    "inst_id": "XAAPL-USDT",
    "direction": "above",
    "price": "235.00",
    "enabled": True,
    "triggered_at": None,
}


class PriceAlert(BaseModel):
    inst_id: str
    direction: AlertDirection
    price: DecimalString
    enabled: bool
    triggered_at: UtcDatetime | None = None

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_ALERT]})


class PriceAlertRequest(BaseModel):
    direction: AlertDirection
    price: DecimalString
    enabled: bool = True


_EXAMPLE_ITEM = {
    "instrument": _EXAMPLE_INSTRUMENT,
    "group": "美股",
    "last_price": "231.42",
    "change_pct_24h": "1.86",
    "volume_24h_quote": "4821334.55",
    "linked_strategy_instance_ids": ["si_0001"],
    "latest_signal": _EXAMPLE_SIGNAL,
    "alert": None,
}


class WatchlistItem(BaseModel):
    """自选列表一行：行情快照 + 关联运行态。"""

    instrument: InstrumentInfo
    group: str
    last_price: DecimalString
    change_pct_24h: DecimalString
    volume_24h_quote: DecimalString
    linked_strategy_instance_ids: list[str] = Field(default_factory=list)
    latest_signal: Signal | None = None
    alert: PriceAlert | None = None

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_ITEM]})


class WatchlistResponse(BaseModel):
    items: list[WatchlistItem]
    groups: list[str]

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [_EXAMPLE_ITEM], "groups": ["美股", "加密"]}]}
    )


class WatchlistAddRequest(BaseModel):
    inst_id: str
    group: str = "默认"


class WatchlistUpdateRequest(BaseModel):
    group: str


class InstrumentSearchResponse(BaseModel):
    items: list[InstrumentRef]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "inst_id": "XAAPL-USDT",
                            "inst_type": "SPOT",
                            "product_key": "AAPL",
                            "asset_type": "tokenized_equity",
                            "base_currency": "XAAPL",
                            "quote_currency": "USDT",
                        },
                        {
                            "inst_id": "AAPL-USDT-SWAP",
                            "inst_type": "SWAP",
                            "product_key": "AAPL",
                            "asset_type": "tokenized_equity",
                            "base_currency": "AAPL",
                            "quote_currency": "USDT",
                        },
                    ]
                }
            ]
        }
    )


class InstrumentDetailResponse(BaseModel):
    instrument: InstrumentInfo
    siblings: list[SiblingQuote]
    latest_signal: Signal | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "instrument": _EXAMPLE_INSTRUMENT,
                    "siblings": [
                        {
                            "inst_id": "AAPL-USDT-SWAP",
                            "inst_type": "SWAP",
                            "last_price": "231.55",
                            "price_spread_pct": "0.06",
                        }
                    ],
                    "latest_signal": _EXAMPLE_SIGNAL,
                }
            ]
        }
    )


class CandleSeriesResponse(BaseModel):
    """K 线窗口。数据不足时 `available_from` 如实反映真实起点，禁止补造。"""

    inst_id: str
    bar: Bar
    data_source: DataSource
    available_from: UtcDatetime | None = None
    available_to: UtcDatetime | None = None
    has_gap: bool = False
    candles: list[Candle]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "inst_id": "XAAPL-USDT",
                    "bar": "1h",
                    "data_source": "okx",
                    "available_from": "2026-11-10T05:00:00Z",
                    "available_to": "2026-11-10T07:00:00Z",
                    "has_gap": False,
                    "candles": [
                        {
                            "open_time": "2026-11-10T07:00:00Z",
                            "open": "229.80",
                            "high": "232.10",
                            "low": "229.44",
                            "close": "231.42",
                            "volume": "1520.335",
                            "is_closed": True,
                            "data_source": "okx",
                        }
                    ],
                }
            ]
        }
    )


class RelatedInstrument(BaseModel):
    inst_id: str
    product_key: str
    asset_type: AssetType
    correlation: DecimalString
    window_days: int


class RelatedInstrumentsResponse(BaseModel):
    inst_id: str
    window_days: int
    items: list[RelatedInstrument]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "inst_id": "XAAPL-USDT",
                    "window_days": 30,
                    "items": [
                        {
                            "inst_id": "XQQQ-USDT",
                            "product_key": "QQQ",
                            "asset_type": "tokenized_equity",
                            "correlation": "0.87",
                            "window_days": 30,
                        }
                    ],
                }
            ]
        }
    )

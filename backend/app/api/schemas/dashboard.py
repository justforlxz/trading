"""首页汇总契约：八个模块各自带状态、时点、原因与内容。

每个模块固定包含 `status`、`as_of`、`error`、`data` 四项：

- `status` 取 `ok`、`stale`、`unavailable`、`unconfigured`；
- `as_of` 是该模块数据的时刻，没有数据时为 `null`；
- `error` 只在非 `ok` 时给出简短原因，不含上游原始响应；
- `data` 在模块不可用时为 `null`，不返回旧值冒充实时值。

顶层另带 `degraded`，把非 `ok` 的模块汇总成一行，便于前端统一显示。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import (
    Bar,
    DataSource,
    DecimalString,
    InstType,
    PositionSide,
    UtcDatetime,
)
from app.api.schemas.correlation import MarketBreadth, MarketResonance

__all__ = [
    "DashboardAccountData",
    "DashboardAccountModule",
    "DashboardActivityItem",
    "DashboardActivityModule",
    "DashboardAlertItem",
    "DashboardAlertsModule",
    "DashboardDegradedItem",
    "DashboardMarketData",
    "DashboardMarketItem",
    "DashboardMarketModule",
    "DashboardModule",
    "DashboardPositionItem",
    "DashboardPositionsData",
    "DashboardPositionsModule",
    "DashboardRecentBacktest",
    "DashboardRiskData",
    "DashboardRiskModule",
    "DashboardStatus",
    "DashboardStrategiesData",
    "DashboardStrategiesModule",
    "DashboardSummaryResponse",
    "DashboardWatchlistData",
    "DashboardWatchlistItem",
    "DashboardWatchlistModule",
    "DashboardWatchlistSummary",
    "MarketSession",
]

DashboardStatus = Literal["ok", "stale", "unavailable", "unconfigured"]
MarketSession = Literal["pre", "regular", "post", "closed"]


class DashboardModule(BaseModel):
    """八个模块共有的四项：状态、数据时刻、简短原因；`data` 由子类补上。"""

    status: DashboardStatus
    as_of: UtcDatetime | None = None
    error: str | None = None


class DashboardMarketItem(BaseModel):
    """一个标的类别在首页上的市场状态、广度与共振。"""

    inst_type: InstType
    session: MarketSession
    primary_source: DataSource
    bar: Bar
    as_of: UtcDatetime
    breadth: MarketBreadth
    resonance: MarketResonance


class DashboardMarketData(BaseModel):
    session: MarketSession
    items: list[DashboardMarketItem]


class DashboardMarketModule(DashboardModule):
    data: DashboardMarketData | None = None


class DashboardAccountData(BaseModel):
    """账户卡内容；派生字段由 `app.positions` 给出，聚合层不重算。"""

    account_id: str
    currency: str
    equity: DecimalString | None = None
    available_equity: DecimalString | None = None
    cash_balance: DecimalString | None = None
    unrealized_pnl: DecimalString | None = None
    used_margin: DecimalString | None = None
    available_margin: DecimalString | None = None
    margin_usage_pct: DecimalString | None = None
    day_pnl: DecimalString | None = None
    day_pnl_basis: Literal["equity_only"] = "equity_only"
    captured_at: UtcDatetime | None = None
    source: str | None = None


class DashboardAccountModule(DashboardModule):
    data: DashboardAccountData | None = None


class DashboardRiskData(BaseModel):
    """风险卡：组合级数值与规则命中数量，不重复展开每条持仓的规则明细。"""

    risk_level: Literal["low", "medium", "high"]
    currency: str
    long_notional: DecimalString
    short_notional: DecimalString
    net_notional: DecimalString
    gross_notional: DecimalString
    margin_usage_pct: DecimalString | None = None
    margin_usage_basis: Literal["margin_ratio", "used_margin"] | None = None
    position_count: int
    near_stop_count: int
    high_leverage_count: int
    missing_stop_count: int
    max_single_instrument_weight_pct: DecimalString | None = None


class DashboardRiskModule(DashboardModule):
    data: DashboardRiskData | None = None


class DashboardPositionItem(BaseModel):
    """首页持仓行：只保留展示需要的字段，完整明细走各自的域接口。"""

    position_ref: str
    source: Literal["exchange", "manual"]
    inst_id: str
    display_symbol: str
    side: PositionSide
    leverage: DecimalString | None = None
    mark_price: DecimalString | None = None
    notional: DecimalString | None = None
    stop_distance_pct: DecimalString | None = None
    unrealized_pnl: DecimalString | None = None


class DashboardPositionsData(BaseModel):
    total: int
    exchange_count: int
    manual_count: int
    exchange_status: Literal["ok", "stale", "unconfigured"]
    items: list[DashboardPositionItem]


class DashboardPositionsModule(DashboardModule):
    data: DashboardPositionsData | None = None


class DashboardWatchlistItem(BaseModel):
    inst_id: str
    display_symbol: str
    name: str
    last_price: DecimalString | None = None
    change_pct_24h: DecimalString | None = None
    trend: Literal["bullish", "bearish", "neutral"] | None = None
    rsi_14: DecimalString | None = None
    data_status: Literal["ok", "partial", "missing"]


class DashboardWatchlistSummary(BaseModel):
    total: int
    bullish: int
    bearish: int
    coverage_pct: DecimalString


class DashboardWatchlistData(BaseModel):
    summary: DashboardWatchlistSummary
    items: list[DashboardWatchlistItem]


class DashboardWatchlistModule(DashboardModule):
    data: DashboardWatchlistData | None = None


class DashboardAlertItem(BaseModel):
    """待处理提醒；当前来源是 B3 的未处置风险事件，B8 合并后换成提醒事件表。"""

    id: str
    type: Literal["risk"]
    severity: str | None = None
    instrument_id: str | None = None
    rule_id: str
    title: str
    detail: str
    status: Literal["pending"]
    triggered_at: UtcDatetime


class DashboardAlertsModule(DashboardModule):
    data: list[DashboardAlertItem] | None = None


class DashboardRecentBacktest(BaseModel):
    """最近 30 天内创建的一次回测；一次回测只代表一个标的，不跨标的求和。"""

    run_id: str
    data_source: DataSource
    window_days: int
    total_return: DecimalString
    max_drawdown: DecimalString
    trade_count: int
    as_of: UtcDatetime


class DashboardStrategiesData(BaseModel):
    total: int
    enabled: int
    running: int
    pending_signals: int | None = None
    recent_backtest: DashboardRecentBacktest | None = None


class DashboardStrategiesModule(DashboardModule):
    data: DashboardStrategiesData | None = None


class DashboardActivityItem(BaseModel):
    id: str
    event_type: str
    object_type: str
    object_id: str
    summary: str
    created_at: UtcDatetime


class DashboardActivityModule(DashboardModule):
    data: list[DashboardActivityItem] | None = None


class DashboardDegradedItem(BaseModel):
    module: str
    status: DashboardStatus
    reason: str
    last_success_at: UtcDatetime | None = None


_EXAMPLE: dict[str, object] = {
    "as_of": "2026-11-13T09:00:00Z",
    "market": {
        "status": "ok",
        "as_of": "2026-11-13T09:00:00Z",
        "error": None,
        "data": {
            "session": "pre",
            "items": [
                {
                    "inst_type": "SPOT",
                    "session": "regular",
                    "primary_source": "okx_spot",
                    "bar": "1d",
                    "as_of": "2026-11-13T09:00:00Z",
                    "breadth": {
                        "advancers": 8,
                        "decliners": 2,
                        "unchanged": 1,
                        "ratio": "4",
                        "participants": 11,
                    },
                    "resonance": {"strength": "0.62", "participants": 11, "window": 20},
                },
                {
                    "inst_type": "SWAP",
                    "session": "pre",
                    "primary_source": "us_equity_proxy",
                    "bar": "1d",
                    "as_of": "2026-11-13T09:00:00Z",
                    "breadth": {
                        "advancers": 5,
                        "decliners": 5,
                        "unchanged": 0,
                        "ratio": "1",
                        "participants": 10,
                    },
                    "resonance": {"strength": "0", "participants": 10, "window": 20},
                },
            ],
        },
    },
    "account": {
        "status": "ok",
        "as_of": "2026-11-13T09:00:00Z",
        "error": None,
        "data": {
            "account_id": "okx-main",
            "currency": "USDT",
            "equity": "1248.60",
            "available_equity": "682.30",
            "cash_balance": "0",
            "unrealized_pnl": "31.84",
            "used_margin": "566.30",
            "available_margin": "682.30",
            "margin_usage_pct": "45.36",
            "day_pnl": None,
            "day_pnl_basis": "equity_only",
            "captured_at": "2026-11-13T09:00:00Z",
            "source": "okx_rest",
        },
    },
    "risk": {
        "status": "ok",
        "as_of": "2026-11-13T09:00:00Z",
        "error": None,
        "data": {
            "risk_level": "medium",
            "currency": "USDT",
            "long_notional": "1851.36",
            "short_notional": "0",
            "net_notional": "1851.36",
            "gross_notional": "1851.36",
            "margin_usage_pct": "45.36",
            "margin_usage_basis": "margin_ratio",
            "position_count": 1,
            "near_stop_count": 0,
            "high_leverage_count": 0,
            "missing_stop_count": 1,
            "max_single_instrument_weight_pct": "100",
        },
    },
    "positions": {
        "status": "ok",
        "as_of": "2026-11-13T09:00:00Z",
        "error": None,
        "data": {
            "total": 1,
            "exchange_count": 1,
            "manual_count": 0,
            "exchange_status": "ok",
            "items": [
                {
                    "position_ref": "exchange:okx-main:123456",
                    "source": "exchange",
                    "inst_id": "AAPL-USDT-SWAP",
                    "display_symbol": "AAPL-USDT",
                    "side": "long",
                    "leverage": "3",
                    "mark_price": "231.42",
                    "notional": "1851.36",
                    "stop_distance_pct": None,
                    "unrealized_pnl": "36.96",
                }
            ],
        },
    },
    "watchlist": {
        "status": "ok",
        "as_of": "2026-11-12T16:00:00Z",
        "error": None,
        "data": {
            "summary": {"total": 1, "bullish": 1, "bearish": 0, "coverage_pct": "100"},
            "items": [
                {
                    "inst_id": "XAAPL-USDT",
                    "display_symbol": "AAPL",
                    "name": "Apple",
                    "last_price": "231.42",
                    "change_pct_24h": "1.86",
                    "trend": "bullish",
                    "rsi_14": "61.4",
                    "data_status": "ok",
                }
            ],
        },
    },
    "alerts": {
        "status": "ok",
        "as_of": None,
        "error": None,
        "data": [],
    },
    "strategies": {
        "status": "ok",
        "as_of": "2026-11-13T09:00:00Z",
        "error": None,
        "data": {
            "total": 2,
            "enabled": 1,
            "running": 0,
            "pending_signals": None,
            "recent_backtest": {
                "run_id": "bt_0001",
                "data_source": "okx_swap",
                "window_days": 30,
                "total_return": "0.124",
                "max_drawdown": "0.061",
                "trade_count": 18,
                "as_of": "2026-11-12T10:00:00Z",
            },
        },
    },
    "activity": {
        "status": "ok",
        "as_of": "2026-11-13T09:00:00Z",
        "error": None,
        "data": [],
    },
    "degraded": [],
}


class DashboardSummaryResponse(BaseModel):
    """首页一次请求返回八个模块；任一模块失败只影响它自己。"""

    as_of: UtcDatetime
    market: DashboardMarketModule
    account: DashboardAccountModule
    risk: DashboardRiskModule
    positions: DashboardPositionsModule
    watchlist: DashboardWatchlistModule
    alerts: DashboardAlertsModule
    strategies: DashboardStrategiesModule
    activity: DashboardActivityModule
    degraded: list[DashboardDegradedItem]

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE]})

"""概览契约：市场驾驶舱一屏所需的账户、敞口、自选、策略与信号。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import DecimalString, ExecutionMode, Signal, StrategyStatus, UtcDatetime
from app.api.schemas.trades import Position

__all__ = [
    "AccountSummary",
    "ExposureSummary",
    "OverviewResponse",
    "StrategyBrief",
    "WatchlistBrief",
]


class AccountSummary(BaseModel):
    equity: DecimalString
    available: DecimalString
    currency: str
    unrealized_pnl: DecimalString
    today_pnl: DecimalString
    mode: ExecutionMode


class ExposureSummary(BaseModel):
    gross_exposure: DecimalString
    net_exposure: DecimalString
    margin_used_pct: DecimalString


class WatchlistBrief(BaseModel):
    inst_id: str
    product_key: str
    last_price: DecimalString
    change_pct_24h: DecimalString


class StrategyBrief(BaseModel):
    instance_id: str
    name: str
    strategy_id: str
    status: StrategyStatus
    latest_signal_at: UtcDatetime | None = None


class OverviewResponse(BaseModel):
    account: AccountSummary
    exposure: ExposureSummary
    positions: list[Position]
    watchlist_highlights: list[WatchlistBrief]
    active_strategies: list[StrategyBrief]
    recent_signals: list[Signal]
    generated_at: UtcDatetime

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "account": {
                        "equity": "10240.55",
                        "available": "8160.00",
                        "currency": "USDT",
                        "unrealized_pnl": "28.64",
                        "today_pnl": "-12.30",
                        "mode": "paper",
                    },
                    "exposure": {
                        "gross_exposure": "1997.15",
                        "net_exposure": "1997.15",
                        "margin_used_pct": "19.5",
                    },
                    "positions": [
                        {
                            "inst_id": "XAAPL-USDT",
                            "inst_type": "SPOT",
                            "product_key": "AAPL",
                            "side": "long",
                            "qty": "8.63",
                            "avg_entry_price": "228.10",
                            "mark_price": "231.42",
                            "notional": "1997.15",
                            "unrealized_pnl": "28.64",
                            "leverage": "1",
                            "liquidation_price": None,
                            "mode": "paper",
                            "strategy_instance_id": "si_0001",
                            "opened_at": "2026-11-09T14:00:00Z",
                        }
                    ],
                    "watchlist_highlights": [
                        {
                            "inst_id": "XAAPL-USDT",
                            "product_key": "AAPL",
                            "last_price": "231.42",
                            "change_pct_24h": "1.86",
                        }
                    ],
                    "active_strategies": [
                        {
                            "instance_id": "si_0001",
                            "name": "AAPL 均线趋势",
                            "strategy_id": "ma_cross",
                            "status": "enabled",
                            "latest_signal_at": "2026-11-10T07:00:00Z",
                        }
                    ],
                    "recent_signals": [
                        {
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
                    ],
                    "generated_at": "2026-11-10T08:00:00Z",
                }
            ]
        }
    )

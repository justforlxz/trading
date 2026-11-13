"""持仓与账户契约：OKX 只读快照、手动持仓与流水。

所有金额、价格、数量都以字符串承载十进制数；时间一律 ISO-8601 UTC。没有快照、
没有行情或没有可算数值时字段为 `null`，不用 0 或相似标的价格冒充。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import DataSource, DecimalString, PositionSide, UtcDatetime

__all__ = [
    "AccountStatus",
    "AccountSummaryResponse",
    "AccountSyncResponse",
    "ExchangePositionItem",
    "ExchangePositionsResponse",
    "ManualPositionCreateRequest",
    "ManualPositionItem",
    "ManualPositionListResponse",
    "ManualPositionUpdateRequest",
    "ManualTradeAction",
    "ManualTradeItem",
    "ManualTradeListResponse",
    "ManualTradeRequest",
]

AccountStatus = Literal["ok", "stale", "unconfigured"]
ManualTradeAction = Literal["add", "reduce", "close", "correct"]


class AccountSummaryResponse(BaseModel):
    """账户卡：最近一条账户快照，以及只在北京时间日初有基准时给出的今日盈亏。"""

    status: AccountStatus
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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "status": "ok",
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
                }
            ]
        }
    )


class AccountSyncResponse(AccountSummaryResponse):
    """一次同步的结果：账户卡 + 本次写入的持仓条数。"""

    positions_synced: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "status": "ok",
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
                    "positions_synced": 1,
                }
            ]
        }
    )


class ExchangePositionItem(BaseModel):
    pos_id: str
    inst_id: str
    display_symbol: str
    name: str
    asset_class: str
    pos_side: PositionSide
    size: DecimalString
    avg_px: DecimalString
    mark_px: DecimalString | None = None
    upl: DecimalString | None = None
    upl_ratio: DecimalString | None = None
    lever: DecimalString | None = None
    mgn_mode: str | None = None
    liq_px: DecimalString | None = None
    margin: DecimalString | None = None


class ExchangePositionsResponse(BaseModel):
    as_of: UtcDatetime | None = None
    status: AccountStatus
    items: list[ExchangePositionItem]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "as_of": "2026-11-13T09:00:00Z",
                    "status": "ok",
                    "items": [
                        {
                            "pos_id": "123456",
                            "inst_id": "AAPL-USDT-SWAP",
                            "display_symbol": "AAPL-USDT",
                            "name": "AAPL",
                            "asset_class": "tokenized_equity",
                            "pos_side": "long",
                            "size": "8",
                            "avg_px": "226.80",
                            "mark_px": "231.42",
                            "upl": "36.96",
                            "upl_ratio": "0.0204",
                            "lever": "3",
                            "mgn_mode": "cross",
                            "liq_px": "151.20",
                            "margin": "604.80",
                        }
                    ],
                }
            ]
        }
    )


class ManualPositionCreateRequest(BaseModel):
    """创建手动持仓；`idempotency_key` 由客户端提供，重复提交不重复入账。"""

    model_config = ConfigDict(extra="forbid")

    inst_id: str = Field(min_length=1)
    side: PositionSide
    quantity: DecimalString
    avg_cost: DecimalString
    stop_px: DecimalString | None = None
    leverage: DecimalString | None = None
    note: str | None = Field(default=None, max_length=512)
    idempotency_key: str = Field(min_length=1, max_length=128)


class ManualPositionUpdateRequest(BaseModel):
    """只允许改止损价、杠杆与备注；数量和成本只能通过流水改变。"""

    model_config = ConfigDict(extra="forbid")

    stop_px: DecimalString | None = None
    leverage: DecimalString | None = None
    note: str | None = Field(default=None, max_length=512)


class ManualTradeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ManualTradeAction
    quantity: DecimalString
    price: DecimalString
    fee: DecimalString = "0"
    occurred_at: UtcDatetime
    note: str | None = Field(default=None, max_length=512)
    idempotency_key: str = Field(min_length=1, max_length=128)


class ManualPositionItem(BaseModel):
    id: str
    inst_id: str
    display_symbol: str
    name: str
    asset_class: str
    side: PositionSide
    quantity: DecimalString
    avg_cost: DecimalString
    stop_px: DecimalString | None = None
    leverage: DecimalString | None = None
    status: Literal["open", "closed"]
    note: str | None = None
    price: DecimalString | None = None
    price_status: Literal["ok", "unavailable"]
    price_source: DataSource | None = None
    market_value: DecimalString | None = None
    unrealized_pnl: DecimalString | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "0f6f6f0e-5b6f-4f0c-9b7a-7e5f8a1d2c34",
                    "inst_id": "AAPL-USDT-SWAP",
                    "display_symbol": "AAPL-USDT",
                    "name": "AAPL",
                    "asset_class": "tokenized_equity",
                    "side": "long",
                    "quantity": "8",
                    "avg_cost": "226.80",
                    "stop_px": "200.00",
                    "leverage": "3",
                    "status": "open",
                    "note": "手动记账",
                    "price": "231.42",
                    "price_status": "ok",
                    "price_source": "okx_swap",
                    "market_value": "1851.36",
                    "unrealized_pnl": "36.96",
                    "created_at": "2026-11-13T09:00:00Z",
                    "updated_at": "2026-11-13T09:00:00Z",
                }
            ]
        }
    )


class ManualPositionListResponse(BaseModel):
    items: list[ManualPositionItem]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"items": ManualPositionItem.model_config["json_schema_extra"]["examples"]}
            ]
        }
    )


class ManualTradeItem(BaseModel):
    id: str
    position_id: str
    action: Literal["open", "add", "reduce", "close", "correct"]
    quantity: DecimalString
    price: DecimalString
    fee: DecimalString
    realized_pnl: DecimalString | None = None
    position_quantity_after: DecimalString
    position_avg_cost_after: DecimalString
    position_status_after: Literal["open", "closed"]
    occurred_at: UtcDatetime
    note: str | None = None
    created_at: UtcDatetime

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "e2a3d4c5-b6f7-4a89-8b0c-1d2e3f4a5b6c",
                    "position_id": "0f6f6f0e-5b6f-4f0c-9b7a-7e5f8a1d2c34",
                    "action": "reduce",
                    "quantity": "3",
                    "price": "240.00",
                    "fee": "0.10",
                    "realized_pnl": "39.50",
                    "position_quantity_after": "5",
                    "position_avg_cost_after": "226.80",
                    "position_status_after": "open",
                    "occurred_at": "2026-11-13T10:00:00Z",
                    "note": "部分卖出",
                    "created_at": "2026-11-13T10:00:00Z",
                }
            ]
        }
    )


class ManualTradeListResponse(BaseModel):
    items: list[ManualTradeItem]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"items": ManualTradeItem.model_config["json_schema_extra"]["examples"]}]
        }
    )

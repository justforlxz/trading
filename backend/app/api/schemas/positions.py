"""持仓与账户契约：OKX 只读快照、手动持仓与流水。

所有金额、价格、数量都以字符串承载十进制数；时间一律 ISO-8601 UTC。没有快照、
没有行情或没有可算数值时字段为 `null`，不用 0 或相似标的价格冒充。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import (
    DataSource,
    DecimalString,
    InstType,
    PositionSide,
    StopStatus,
    UtcDatetime,
)

__all__ = [
    "AccountStatus",
    "AccountSummaryResponse",
    "AccountSyncResponse",
    "CurvePointItem",
    "EquityCurveResponse",
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
    "MergedPositionItem",
    "MergedPositionsResponse",
    "NotionalStatus",
    "OrderHistoryItem",
    "OrderHistoryResponse",
    "OrderScope",
    "PositionCardItem",
    "PositionCardsResponse",
    "StopStatus",
]

AccountStatus = Literal["ok", "stale", "unconfigured"]
#: 名义合计是否完整；`partial` 表示有持仓没行情，界面必须在数字前标 `≥`。
NotionalStatus = Literal["exact", "partial"]

#: 订单弹窗的筛选：全部 / 挂单 / 历史。
OrderScope = Literal["all", "open", "history"]
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
    position_notional: DecimalString | None = None
    position_notional_at: UtcDatetime | None = None
    gross_notional: DecimalString | None = None
    net_notional: DecimalString | None = None
    notional_status: NotionalStatus = "partial"
    margin_used: DecimalString | None = None
    margin_usage_floor: bool = True
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
                    "position_notional": "1851.36",
                    "position_notional_at": "2026-11-13T09:00:00Z",
                    "gross_notional": "1851.36",
                    "net_notional": "1851.36",
                    "notional_status": "exact",
                    "margin_used": "617.12",
                    "margin_usage_floor": False,
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
                    "position_notional": "1851.36",
                    "position_notional_at": "2026-11-13T09:00:00Z",
                    "gross_notional": "1851.36",
                    "net_notional": "1851.36",
                    "notional_status": "exact",
                    "margin_used": "617.12",
                    "margin_usage_floor": False,
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


class MergedPositionItem(BaseModel):
    """`GET /api/positions` 的一行：两种来源统一字段，来源专属字段可为空。"""

    position_ref: str
    source: Literal["exchange", "manual"]
    inst_id: str
    display_symbol: str
    name: str
    asset_class: str
    side: PositionSide
    size: DecimalString
    avg_px: DecimalString
    mark_px: DecimalString | None = None
    upl: DecimalString | None = None
    upl_ratio: DecimalString | None = None
    lever: DecimalString | None = None
    mgn_mode: str | None = None
    liq_px: DecimalString | None = None
    margin: DecimalString | None = None
    notional: DecimalString | None = None
    stop_px: DecimalString | None = None
    stop_distance_pct: DecimalString | None = None
    price_status: Literal["ok", "unavailable"] | None = None
    updated_at: UtcDatetime | None = None


class MergedPositionsResponse(BaseModel):
    """OKX 与手动持仓的合并视图；`exchange_status` 只说明交易所同步状态。"""

    as_of: UtcDatetime | None = None
    exchange_status: AccountStatus
    items: list[MergedPositionItem]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "as_of": "2026-11-13T09:00:00Z",
                    "exchange_status": "ok",
                    "items": [
                        {
                            "position_ref": "exchange:okx-main:123456",
                            "source": "exchange",
                            "inst_id": "AAPL-USDT-SWAP",
                            "display_symbol": "AAPL-USDT",
                            "name": "AAPL",
                            "asset_class": "tokenized_equity",
                            "side": "long",
                            "size": "8",
                            "avg_px": "226.80",
                            "mark_px": "231.42",
                            "upl": "36.96",
                            "upl_ratio": "0.0204",
                            "lever": "3",
                            "mgn_mode": "cross",
                            "liq_px": "151.20",
                            "margin": "604.80",
                            "notional": "1851.36",
                            "stop_px": None,
                            "stop_distance_pct": None,
                            "price_status": None,
                            "updated_at": "2026-11-13T09:00:00Z",
                        },
                        {
                            "position_ref": "manual:0f6f6f0e-5b6f-4f0c-9b7a-7e5f8a1d2c34",
                            "source": "manual",
                            "inst_id": "AAPL-USDT-SWAP",
                            "display_symbol": "AAPL-USDT",
                            "name": "AAPL",
                            "asset_class": "tokenized_equity",
                            "side": "long",
                            "size": "2",
                            "avg_px": "55",
                            "mark_px": "60.5",
                            "upl": "11",
                            "upl_ratio": None,
                            "lever": "2",
                            "mgn_mode": None,
                            "liq_px": None,
                            "margin": None,
                            "notional": "121",
                            "stop_px": "58",
                            "stop_distance_pct": "4.132231404959",
                            "price_status": "ok",
                            "updated_at": "2026-11-13T09:00:00Z",
                        },
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


class CurvePointItem(BaseModel):
    """曲线上的一个点；`value` 是该时刻的快照值，不做插值。"""

    at: UtcDatetime
    value: DecimalString


class EquityCurveResponse(BaseModel):
    """一段区间的权益曲线。

    `available=false` 表示这段区间还没有足够的数据（快照只有十天时，一个月窗口
    只有三分之一），此时 `points` 一定为空，界面显示「这段区间还没有数据」，
    **不画线**。`first_snapshot_at` 用于说明「快照自 … 起记录」。
    """

    range: str
    available: bool
    change_pct: DecimalString | None = None
    points: list[CurvePointItem]
    first_snapshot_at: UtcDatetime | None = None
    last_snapshot_at: UtcDatetime | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "range": "1d",
                    "available": True,
                    "change_pct": "2.33",
                    "first_snapshot_at": "2026-11-15T00:00:00Z",
                    "last_snapshot_at": "2026-11-25T13:51:00Z",
                    "points": [
                        {"at": "2026-11-25T12:51:00Z", "value": "412.60"},
                        {"at": "2026-11-25T13:51:00Z", "value": "413.45"},
                    ],
                }
            ]
        }
    )


class PositionCardItem(BaseModel):
    """一张持仓卡片需要的全部事实，盈亏、占比与止损距离都由后端算好。"""

    pos_id: str
    inst_id: str
    display_symbol: str
    name: str
    asset_class: str
    #: 标的类别：卡片据此标出「现货 / 永续」，同一标的的两种形态才不会重名。
    #: 标的还没同步时为 `null`，界面不猜形态。
    inst_type: InstType | None = None
    pos_side: PositionSide
    size: DecimalString
    avg_px: DecimalString
    mark_px: DecimalString | None = None
    #: 标记价的来源：`okx_rest` / `okx_ws` 是交易所随持仓下发的，`okx_spot` 这类是
    #: 已落库 K 线的来源，`okx_ticker` 是库里没有 K 线时读的一次实时报价。
    mark_px_source: str | None = None
    #: 这个价格成立的时刻：K 线取收盘时刻，实时报价取上游报价时间，交易所随持仓
    #: 下发的按快照时刻。两个价格来源混在一页时，靠它说明哪个是旧的。
    mark_px_at: UtcDatetime | None = None
    #: 这个价格是否已经过期（价格时刻早于「一个日线周期」以前）。过期的价格是最后一次
    #: 已知价，界面必须显式标出，不能和实时价并列展示。
    mark_px_stale: bool = False
    #: 过期了几天（向上取整）；没过期时为 `null`。天数由后端算，前端只负责展示。
    mark_px_age_days: int | None = None
    upl: DecimalString | None = None
    upl_ratio: DecimalString | None = None
    lever: DecimalString | None = None
    mgn_mode: str | None = None
    liq_px: DecimalString | None = None
    margin: DecimalString | None = None
    notional: DecimalString | None = None
    weight_pct: DecimalString | None = None
    #: 该类别有没有止损概念：现货没有止损，界面留空而不是显示「未取到」。
    stop_supported: bool
    stop_status: StopStatus
    stop_px: DecimalString | None = None
    stop_distance_pct: DecimalString | None = None
    upl_curve: list[CurvePointItem]


class PositionCardsResponse(BaseModel):
    """持仓卡片列表，已按未实现盈亏绝对值降序。

    `hidden_dust_count` 是展示层隐藏的尘埃条数；快照里一行都没删，`items` 合计的
    `weight_pct` 因此仍是 100%。
    """

    as_of: UtcDatetime | None = None
    status: AccountStatus
    items: list[PositionCardItem]
    hidden_dust_count: int = 0

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "as_of": "2026-11-25T13:51:00Z",
                    "status": "ok",
                    "hidden_dust_count": 0,
                    "items": [
                        {
                            "pos_id": "GOOGL-USDT-SWAP:long",
                            "inst_id": "GOOGL-USDT-SWAP",
                            "display_symbol": "GOOGL-USDT",
                            "name": "Alphabet",
                            "asset_class": "equity_perp",
                            "inst_type": "SWAP",
                            "pos_side": "long",
                            "size": "2.09",
                            "avg_px": "269.34",
                            "mark_px": "276.71",
                            "mark_px_source": "okx_rest",
                            "mark_px_at": "2026-11-25T13:51:00Z",
                            "mark_px_stale": False,
                            "mark_px_age_days": None,
                            "upl": "15.40",
                            "upl_ratio": "0.0274",
                            "lever": "10",
                            "mgn_mode": "isolated",
                            "liq_px": None,
                            "margin": "57.83",
                            "notional": "578.32",
                            "weight_pct": "79.12",
                            "stop_supported": True,
                            "stop_status": "none",
                            "stop_px": None,
                            "stop_distance_pct": None,
                            "upl_curve": [
                                {"at": "2026-11-25T12:51:00Z", "value": "12.10"},
                                {"at": "2026-11-25T13:51:00Z", "value": "15.40"},
                            ],
                        }
                    ],
                }
            ]
        }
    )


class OrderHistoryItem(BaseModel):
    """单标的一笔订单；`is_open` 区分挂单与历史，`pnl` / `fee` 缺失时为 `null`。"""

    order_id: str
    side: Literal["buy", "sell"]
    order_type: str
    price: DecimalString | None = None
    avg_px: DecimalString | None = None
    qty: DecimalString
    filled_qty: DecimalString
    pnl: DecimalString | None = None
    fee: DecimalString | None = None
    status: str
    is_open: bool
    ts: UtcDatetime


class OrderHistoryResponse(BaseModel):
    """单标的订单历史；近 7 天来自 `orders-history`，更早来自归档（最多 3 个月）。"""

    inst_id: str
    scope: OrderScope
    window_days: int
    items: list[OrderHistoryItem]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "inst_id": "BTC-USDT-SWAP",
                    "scope": "all",
                    "window_days": 90,
                    "items": [
                        {
                            "order_id": "3123456789",
                            "side": "sell",
                            "order_type": "limit",
                            "price": "60520",
                            "avg_px": "60520",
                            "qty": "0.2",
                            "filled_qty": "0.2",
                            "pnl": "1.84",
                            "fee": "-0.03",
                            "status": "filled",
                            "is_open": False,
                            "ts": "2026-11-25T09:09:00Z",
                        }
                    ],
                }
            ]
        }
    )

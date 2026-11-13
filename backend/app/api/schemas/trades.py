"""交易契约：持仓、订单、成交、信号、交易日志与执行模式。

执行模式切换（manual / paper / live）是资金安全的显式动作：切到实盘必须带
`acknowledge_risk=true`（decisions.md Q4），界面二次确认后提交。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import (
    DecimalString,
    ExecutionMode,
    InstType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    Signal,
    UtcDatetime,
)

__all__ = [
    "ExecutionModeRequest",
    "ExecutionStateResponse",
    "Fill",
    "FillListResponse",
    "Order",
    "OrderCreateRequest",
    "OrderListResponse",
    "Position",
    "PositionListResponse",
    "SignalListResponse",
]


class Position(BaseModel):
    inst_id: str
    inst_type: InstType
    product_key: str
    side: PositionSide
    qty: DecimalString
    avg_entry_price: DecimalString
    mark_price: DecimalString
    notional: DecimalString
    unrealized_pnl: DecimalString
    leverage: DecimalString
    liquidation_price: DecimalString | None = None
    mode: ExecutionMode
    strategy_instance_id: str | None = None
    opened_at: UtcDatetime


class PositionListResponse(BaseModel):
    mode: ExecutionMode
    items: list[Position]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "mode": "paper",
                    "items": [
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
                }
            ]
        }
    )


_EXAMPLE_ORDER = {
    "order_id": "ord_0001",
    "client_order_id": "cli_9f2a",
    "inst_id": "XAAPL-USDT",
    "inst_type": "SPOT",
    "side": "buy",
    "order_type": "limit",
    "price": "228.10",
    "qty": "8.63",
    "filled_qty": "8.63",
    "avg_fill_price": "228.10",
    "status": "filled",
    "reduce_only": False,
    "mode": "paper",
    "strategy_instance_id": "si_0001",
    "created_at": "2026-11-09T13:59:40Z",
    "updated_at": "2026-11-09T14:00:02Z",
}


class Order(BaseModel):
    order_id: str
    client_order_id: str
    inst_id: str
    inst_type: InstType
    side: OrderSide
    order_type: OrderType
    price: DecimalString | None = None
    qty: DecimalString
    filled_qty: DecimalString
    avg_fill_price: DecimalString | None = None
    status: OrderStatus
    reduce_only: bool
    mode: ExecutionMode
    strategy_instance_id: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_ORDER]})


class OrderListResponse(BaseModel):
    items: list[Order]
    total: int

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [_EXAMPLE_ORDER], "total": 1}]}
    )


class OrderCreateRequest(BaseModel):
    """手动确认下单。`client_order_id` 留空时由服务端生成，用于幂等。"""

    inst_id: str
    side: OrderSide
    order_type: OrderType
    qty: DecimalString
    price: DecimalString | None = None
    reduce_only: bool = False
    acknowledge_risk: bool = False
    client_order_id: str | None = None


class Fill(BaseModel):
    fill_id: str
    order_id: str
    inst_id: str
    side: OrderSide
    price: DecimalString
    qty: DecimalString
    fee: DecimalString
    fee_currency: str
    filled_at: UtcDatetime


class FillListResponse(BaseModel):
    items: list[Fill]
    total: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "fill_id": "fill_0001",
                            "order_id": "ord_0001",
                            "inst_id": "XAAPL-USDT",
                            "side": "buy",
                            "price": "228.10",
                            "qty": "8.63",
                            "fee": "0.98",
                            "fee_currency": "USDT",
                            "filled_at": "2026-11-09T14:00:02Z",
                        }
                    ],
                    "total": 1,
                }
            ]
        }
    )


class SignalListResponse(BaseModel):
    items: list[Signal]
    total: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
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
                    "total": 1,
                }
            ]
        }
    )


class ExecutionStateResponse(BaseModel):
    mode: ExecutionMode
    auto_trading_enabled: bool
    emergency_stop: bool
    live_acknowledged_at: UtcDatetime | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "mode": "paper",
                    "auto_trading_enabled": False,
                    "emergency_stop": False,
                    "live_acknowledged_at": None,
                }
            ]
        }
    )


class ExecutionModeRequest(BaseModel):
    mode: ExecutionMode
    acknowledge_risk: bool = False

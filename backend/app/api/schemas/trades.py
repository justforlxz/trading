"""交易契约：持仓、订单、成交、信号、交易日志与执行模式。

执行模式切换（manual / paper / live）是资金安全的显式动作：切到实盘必须带
`acknowledge_risk=true`（decisions.md Q4），界面二次确认后提交。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import (
    Bar,
    DecimalString,
    ExecutionMode,
    InstType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    Signal,
    StrategyStatus,
    UtcDatetime,
)

__all__ = [
    "ExecutionModeRequest",
    "ExecutionStateResponse",
    "Fill",
    "FillListResponse",
    "JournalCashFlow",
    "JournalCategory",
    "JournalEntry",
    "JournalFill",
    "JournalListResponse",
    "JournalOrder",
    "JournalPosition",
    "JournalReturnPoint",
    "JournalSignal",
    "Order",
    "OrderCreateRequest",
    "OrderListResponse",
    "Position",
    "PositionListResponse",
    "SignalListResponse",
    "StrategyJournalSummary",
]

JournalCategory = Literal[
    "signal",
    "order",
    "fill",
    "mode_change",
    "risk_block",
    "settings",
    "confirmation",
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


class JournalEntry(BaseModel):
    entry_id: str
    category: JournalCategory
    message: str
    inst_id: str | None = None
    created_at: UtcDatetime


class JournalCashFlow(BaseModel):
    """一笔成交引起的资金变化：买入为负、卖出为正，手续费已计入。"""

    at: UtcDatetime
    inst_id: str
    amount: DecimalString


class JournalReturnPoint(BaseModel):
    """平仓后的累计实际收益；没有平仓时曲线为空。"""

    at: UtcDatetime
    value: DecimalString


class StrategyJournalSummary(BaseModel):
    """一个策略实例的配置、回测预期与实际成交收益。

    两个收益各自带来源：`expected_source` 指向具体回测运行，`actual_source` 指向
    具体成交批次。它们是两条独立的读取路径，不是同一个值的两种名字。
    """

    instance_id: str
    strategy_id: str
    strategy_version: str
    name: str
    bar: Bar
    lifecycle_status: StrategyStatus
    execution_mode: ExecutionMode
    params: dict[str, object]
    inst_ids: list[str]
    expected_return: DecimalString | None = None
    expected_source: str
    actual_return: DecimalString
    actual_source: str
    net_cash_flow: DecimalString
    fill_count: int
    cash_flow: list[JournalCashFlow] = []
    actual_curve: list[JournalReturnPoint] = []


class JournalPosition(BaseModel):
    product_key: str
    inst_type: InstType
    side: PositionSide
    qty: DecimalString
    avg_cost: DecimalString
    leverage: DecimalString | None = None
    liquidation_price: DecimalString | None = None
    mode: ExecutionMode


class JournalOrder(BaseModel):
    client_order_id: str
    order_id: str
    inst_id: str
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


class JournalFill(BaseModel):
    fill_id: str
    order_id: str
    inst_id: str
    side: OrderSide
    price: DecimalString
    qty: DecimalString
    fee: DecimalString
    fee_currency: str
    filled_at: UtcDatetime
    strategy_instance_id: str | None = None


class JournalSignal(BaseModel):
    signal_id: str
    instance_id: str
    inst_id: str
    inst_type: InstType
    side: PositionSide
    strength: float
    price: DecimalString | None = None
    reason: str
    generated_at: UtcDatetime
    target_weight: DecimalString | None = None


class JournalListResponse(BaseModel):
    """Trades 页的只读聚合：策略对照、持仓、订单、成交、信号与日志条目。"""

    mode: ExecutionMode = "manual"
    strategies: list[StrategyJournalSummary] = []
    positions: list[JournalPosition] = []
    orders: list[JournalOrder] = []
    fills: list[JournalFill] = []
    signals: list[JournalSignal] = []
    items: list[JournalEntry]
    total: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "entry_id": "jrn_0001",
                            "category": "mode_change",
                            "message": "执行模式 paper -> live, 已二次确认风险",
                            "inst_id": None,
                            "created_at": "2026-11-10T06:10:00Z",
                        }
                    ],
                    "total": 1,
                    "mode": "paper",
                    "strategies": [
                        {
                            "instance_id": "si_0001",
                            "strategy_id": "relative_value",
                            "strategy_version": "1.0.0",
                            "name": "BTC/ETH 相对价值",
                            "bar": "1h",
                            "lifecycle_status": "paper_trading",
                            "execution_mode": "paper",
                            "params": {"reversion_window": 20},
                            "inst_ids": ["XAAPL-USDT"],
                            "expected_return": "0.0432",
                            "expected_source": "backtest:bt_0001:metrics.total_return",
                            "actual_return": "0.0121",
                            "actual_source": "execution:fills:2",
                            "net_cash_flow": "-1971.79",
                            "fill_count": 2,
                            "cash_flow": [
                                {
                                    "at": "2026-11-09T14:00:02Z",
                                    "inst_id": "XAAPL-USDT",
                                    "amount": "-1968.92",
                                }
                            ],
                            "actual_curve": [{"at": "2026-11-10T06:10:00Z", "value": "0.0121"}],
                        }
                    ],
                    "positions": [
                        {
                            "product_key": "AAPL",
                            "inst_type": "SPOT",
                            "side": "long",
                            "qty": "8.63",
                            "avg_cost": "228.10",
                            "leverage": None,
                            "liquidation_price": None,
                            "mode": "paper",
                        }
                    ],
                    "orders": [
                        {
                            "client_order_id": "cli_9f2a",
                            "order_id": "ord_0001",
                            "inst_id": "XAAPL-USDT",
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
                    ],
                    "fills": [
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
                            "strategy_instance_id": "si_0001",
                        }
                    ],
                    "signals": [
                        {
                            "signal_id": "sig_0001",
                            "instance_id": "si_0001",
                            "inst_id": "XAAPL-USDT",
                            "inst_type": "SPOT",
                            "side": "long",
                            "strength": 0.8,
                            "price": "231.42",
                            "reason": "MA20 上穿 MA60",
                            "generated_at": "2026-11-10T07:00:00Z",
                            "target_weight": "0.25",
                        }
                    ],
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

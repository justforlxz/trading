"""策略契约：策略模板定义（Definition）与可启停的实例（Instance）严格分离。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import (
    Bar,
    ExecutionMode,
    ParamSpec,
    ParamValue,
    SignalAction,
    StrategyStatus,
    UtcDatetime,
)

__all__ = [
    "StrategyCatalogResponse",
    "StrategyDefinition",
    "StrategyInstance",
    "StrategyInstanceCreateRequest",
    "StrategyInstanceListResponse",
    "StrategyInstanceUpdateRequest",
]


class StrategyDefinition(BaseModel):
    """策略模板：一个模板可派生多个独立配置的实例。"""

    strategy_id: str
    name: str
    version: str
    summary: str
    params: list[ParamSpec]
    required_indicators: list[str]
    required_bars: list[Bar]
    emitted_actions: list[SignalAction]


class StrategyCatalogResponse(BaseModel):
    items: list[StrategyDefinition]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "strategy_id": "ma_cross",
                            "name": "MA Cross",
                            "version": "1.0.0",
                            "summary": "快慢均线交叉产生多空信号。",
                            "params": [
                                {
                                    "name": "fast",
                                    "title": "快线周期",
                                    "kind": "int",
                                    "default": 20,
                                    "minimum": 2,
                                    "maximum": 200,
                                },
                                {
                                    "name": "slow",
                                    "title": "慢线周期",
                                    "kind": "int",
                                    "default": 60,
                                    "minimum": 3,
                                    "maximum": 500,
                                },
                            ],
                            "required_indicators": ["sma"],
                            "required_bars": ["1h", "4h", "1d"],
                            "emitted_actions": ["BUY", "SELL", "HOLD"],
                        }
                    ]
                }
            ]
        }
    )


_EXAMPLE_INSTANCE = {
    "instance_id": "si_0001",
    "strategy_id": "ma_cross",
    "strategy_version": "1.0.0",
    "name": "AAPL 均线趋势",
    "bar": "1h",
    "params": {"fast": 20, "slow": 60},
    "inst_ids": ["XAAPL-USDT"],
    "status": "enabled",
    "execution_mode": "paper",
    "latest_signal_at": "2026-11-10T07:00:00Z",
    "created_at": "2026-11-08T02:15:00Z",
    "updated_at": "2026-11-10T07:00:00Z",
}


class StrategyInstance(BaseModel):
    instance_id: str
    strategy_id: str
    strategy_version: str
    name: str
    bar: Bar
    params: dict[str, ParamValue]
    inst_ids: list[str]
    status: StrategyStatus
    execution_mode: ExecutionMode
    latest_signal_at: UtcDatetime | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_INSTANCE]})


class StrategyInstanceListResponse(BaseModel):
    items: list[StrategyInstance]
    total: int

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [_EXAMPLE_INSTANCE], "total": 1}]}
    )


class StrategyInstanceCreateRequest(BaseModel):
    strategy_id: str
    name: str
    bar: Bar
    params: dict[str, ParamValue] = Field(default_factory=dict)
    inst_ids: list[str]


class StrategyInstanceUpdateRequest(BaseModel):
    """PATCH 语义：只落显式提交的字段。"""

    name: str | None = None
    params: dict[str, ParamValue] | None = None
    inst_ids: list[str] | None = None
    status: StrategyStatus | None = None

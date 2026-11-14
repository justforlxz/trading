"""v6 用户策略契约：策略、不可变版本、标的集合与回测关联。

策略是身份与展示属性，版本才是可复现输入。列表返回当前版本与最近回测摘要；详情
返回当前版本的规则、参数、标的与版本目录；版本接口新建下一版，旧版本不提供修改
入口。这里不发布审批、执行或旧实例字段。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.schemas.common import Bar, DataSource, DecimalString, UtcDatetime

__all__ = [
    "InstrumentStrategy",
    "InstrumentStrategyListResponse",
    "StrategyBacktestSummary",
    "StrategyCreateRequest",
    "StrategyCreatedResponse",
    "StrategyDetail",
    "StrategyDirection",
    "StrategyInstrumentUpdateRequest",
    "StrategyListResponse",
    "StrategyRecordStatus",
    "StrategySummary",
    "StrategyUpdateRequest",
    "StrategyUpdatedResponse",
    "StrategyVersionCreateRequest",
    "StrategyVersionDetail",
    "StrategyVersionListResponse",
    "StrategyVersionSummary",
]

StrategyRecordStatus = Literal["draft", "validated", "enabled", "paused", "archived"]
StrategyDirection = Literal["long_only", "short_only", "long_short"]


_EXAMPLE_BACKTEST = {
    "run_id": "bt_0001",
    "strategy_version_id": "sv_0001",
    "data_source": "okx_spot",
    "total_return_pct": "12.4055",
    "max_drawdown_pct": "6.12",
    "trade_count": 37,
    "backtest_start_date": "2026-10-01",
    "backtest_end_date": "2026-11-01",
    "created_at": "2026-11-10T01:20:00Z",
}

_EXAMPLE_VERSION = {
    "version_id": "sv_0001",
    "version": 1,
    "timeframe": "1d",
    "direction": "long_only",
    "change_note": "初始版本",
    "created_at": "2026-11-08T02:15:00Z",
}

_EXAMPLE_SUMMARY = {
    "id": "st_0001",
    "name": "AAPL 趋势",
    "category": "directional",
    "description": "均线趋势跟随",
    "status": "draft",
    "current_version_id": "sv_0001",
    "current_version": 1,
    "timeframe": "1d",
    "direction": "long_only",
    "instrument_count": 1,
    "latest_backtest": _EXAMPLE_BACKTEST,
    "created_at": "2026-11-08T02:15:00Z",
    "updated_at": "2026-11-10T07:00:00Z",
}

_RULE = {
    "timeframe": "1d",
    "direction": "long_only",
    "entry": {"all": [{"left": "MA(20)", "op": ">", "right": "MA(60)"}]},
    "exit": {"any": [{"left": "MA(20)", "op": "<", "right": "MA(60)"}]},
    "position_sizing": {"type": "equal_weight", "weight": 0.3333, "max_positions": 3},
}

_EXAMPLE_VERSION_DETAIL = {
    "version_id": "sv_0001",
    "strategy_id": "st_0001",
    "version": 1,
    "timeframe": "1d",
    "direction": "long_only",
    "rule_json": _RULE,
    "parameters": {"fast": 20, "slow": 60},
    "position_sizing": {"type": "equal_weight", "weight": 0.3333, "max_positions": 3},
    "cost_model": {"fee_bps": "10", "slippage_bps": "5"},
    "change_note": "初始版本",
    "instrument_ids": ["XAAPL-USDT"],
    "created_at": "2026-11-08T02:15:00Z",
}

_EXAMPLE_DETAIL = {
    "id": "st_0001",
    "name": "AAPL 趋势",
    "category": "directional",
    "description": "均线趋势跟随",
    "status": "draft",
    "current_version_id": "sv_0001",
    "current_version": 1,
    "timeframe": "1d",
    "direction": "long_only",
    "rule_json": _RULE,
    "parameters": {"fast": 20, "slow": 60},
    "position_sizing": {"type": "equal_weight", "weight": 0.3333, "max_positions": 3},
    "cost_model": {"fee_bps": "10", "slippage_bps": "5"},
    "instrument_ids": ["XAAPL-USDT"],
    "versions": [_EXAMPLE_VERSION],
    "latest_backtest": _EXAMPLE_BACKTEST,
    "created_at": "2026-11-08T02:15:00Z",
    "updated_at": "2026-11-10T07:00:00Z",
}


class StrategyBacktestSummary(BaseModel):
    """列表与详情里的最近一次回测摘要；指标已是百分数。"""

    run_id: str
    strategy_version_id: str
    data_source: DataSource
    total_return_pct: DecimalString
    max_drawdown_pct: DecimalString
    trade_count: int
    backtest_start_date: date
    backtest_end_date: date
    created_at: UtcDatetime


class StrategyVersionSummary(BaseModel):
    version_id: str
    version: int
    timeframe: Bar
    direction: StrategyDirection
    change_note: str | None = None
    created_at: UtcDatetime


class StrategySummary(BaseModel):
    id: str
    name: str
    category: str
    description: str | None = None
    status: StrategyRecordStatus
    current_version_id: str
    current_version: int
    timeframe: Bar
    direction: StrategyDirection
    instrument_count: int
    latest_backtest: StrategyBacktestSummary | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class StrategyListResponse(BaseModel):
    items: list[StrategySummary]
    next_cursor: str | None = None

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [_EXAMPLE_SUMMARY], "next_cursor": None}]}
    )


class StrategyDetail(BaseModel):
    id: str
    name: str
    category: str
    description: str | None = None
    status: StrategyRecordStatus
    current_version_id: str
    current_version: int
    timeframe: Bar
    direction: StrategyDirection
    rule_json: dict[str, Any]
    parameters: dict[str, Any]
    position_sizing: dict[str, Any] | None = None
    cost_model: dict[str, Any] | None = None
    instrument_ids: list[str]
    versions: list[StrategyVersionSummary]
    latest_backtest: StrategyBacktestSummary | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_DETAIL]})


class StrategyVersionDetail(BaseModel):
    version_id: str
    strategy_id: str
    version: int
    timeframe: Bar
    direction: StrategyDirection
    rule_json: dict[str, Any]
    parameters: dict[str, Any]
    position_sizing: dict[str, Any] | None = None
    cost_model: dict[str, Any] | None = None
    change_note: str | None = None
    instrument_ids: list[str]
    created_at: UtcDatetime

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_VERSION_DETAIL]})


class StrategyVersionListResponse(BaseModel):
    items: list[StrategyVersionDetail]
    total: int

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [_EXAMPLE_VERSION_DETAIL], "total": 1}]}
    )


class StrategyCreatedResponse(BaseModel):
    id: str
    version_id: str
    status: StrategyRecordStatus
    created_at: UtcDatetime

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "st_0001",
                    "version_id": "sv_0001",
                    "status": "draft",
                    "created_at": "2026-11-08T02:15:00Z",
                }
            ]
        }
    )


class StrategyUpdatedResponse(BaseModel):
    id: str
    version_id: str
    status: StrategyRecordStatus
    updated_at: UtcDatetime

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "st_0001",
                    "version_id": "sv_0002",
                    "status": "draft",
                    "updated_at": "2026-11-10T07:00:00Z",
                }
            ]
        }
    )


class StrategyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    category: str
    description: str | None = None
    timeframe: Bar
    direction: StrategyDirection
    rule_json: dict[str, Any]
    parameters: dict[str, Any] = Field(default_factory=dict)
    instrument_ids: list[str]
    cost_model: dict[str, Any] | None = None
    position_sizing: dict[str, Any] | None = None
    change_note: str | None = None


class StrategyUpdateRequest(BaseModel):
    """只改提交的字段；出现任一版本字段时新建下一版。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    category: str | None = None
    description: str | None = None
    status: StrategyRecordStatus | None = None
    timeframe: Bar | None = None
    direction: StrategyDirection | None = None
    rule_json: dict[str, Any] | None = None
    parameters: dict[str, Any] | None = None
    instrument_ids: list[str] | None = None
    cost_model: dict[str, Any] | None = None
    position_sizing: dict[str, Any] | None = None
    change_note: str | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> StrategyUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("更新请求至少需要一项字段")
        return self


class StrategyVersionCreateRequest(BaseModel):
    """新建下一版：未提交的字段沿用当前版本。"""

    model_config = ConfigDict(extra="forbid")

    timeframe: Bar | None = None
    direction: StrategyDirection | None = None
    rule_json: dict[str, Any] | None = None
    parameters: dict[str, Any] | None = None
    instrument_ids: list[str] | None = None
    cost_model: dict[str, Any] | None = None
    position_sizing: dict[str, Any] | None = None
    change_note: str | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> StrategyVersionCreateRequest:
        if not self.model_fields_set:
            raise ValueError("版本请求至少需要一项字段")
        return self


class StrategyInstrumentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_ids: list[str]


_EXAMPLE_INSTRUMENT_STRATEGY = {
    "strategy_id": "st_0001",
    "name": "AAPL 趋势",
    "category": "directional",
    "status": "draft",
    "current_version_id": "sv_0001",
    "current_version": 1,
    "timeframe": "1d",
    "direction": "long_only",
    "instrument_ids": ["XAAPL-USDT"],
    "linked_version_ids": ["sv_0001"],
    "recent_backtest": _EXAMPLE_BACKTEST,
    "updated_at": "2026-11-10T07:00:00Z",
}


class InstrumentStrategy(BaseModel):
    strategy_id: str
    name: str
    category: str
    status: StrategyRecordStatus
    current_version_id: str
    current_version: int
    timeframe: Bar
    direction: StrategyDirection
    instrument_ids: list[str]
    linked_version_ids: list[str]
    recent_backtest: StrategyBacktestSummary | None = None
    updated_at: UtcDatetime


class InstrumentStrategyListResponse(BaseModel):
    items: list[InstrumentStrategy]

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [_EXAMPLE_INSTRUMENT_STRATEGY]}]}
    )

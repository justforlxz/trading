"""策略契约：策略模板定义（Definition）与可启停的实例（Instance）严格分离。

模板目录来自代码注册表，实例是用户配置；回放（`StrategyReplay`）是「按历史行情把
模板重算一遍」的执行记录，目标组合直接复用 `TargetPortfolio`，不另立一套形状。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import (
    Bar,
    DecimalString,
    ExecutionMode,
    ParamSpec,
    ParamValue,
    SignalAction,
    StrategyStatus,
    TargetPortfolio,
    UtcDatetime,
)

__all__ = [
    "StrategyCatalogResponse",
    "StrategyDefinition",
    "StrategyInstance",
    "StrategyInstanceCreateRequest",
    "StrategyInstanceListResponse",
    "StrategyInstanceUpdateRequest",
    "StrategyReplay",
    "StrategyReplayListResponse",
    "StrategyReplayPoint",
    "StrategyReplayRequest",
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
    "status": "paper_trading",
    "enabled": True,
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
    enabled: bool = True
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
    """PATCH 语义：只落显式提交的字段。

    生命周期阶段**不在这条端点上改**：阶段推进只经 `/api/approvals` 的状态机，
    否则一次 PATCH 就能从草稿跳到实盘运行，绕过人工审核、历史回测与量化验证
    （`docs/prd/v2.md` §三.5「任何阶段都不能被跳过」）。提交 `status` 会因
    `extra="forbid"` 直接 422，不会静默忽略。

    `enabled` 是实例的启停开关，只决定它是否产出信号，不改变生命周期阶段。
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    params: dict[str, ParamValue] | None = None
    inst_ids: list[str] | None = None
    enabled: bool | None = None


class StrategyReplayRequest(BaseModel):
    """回放区间：左闭右闭，`end` 那一根已收盘 K 线也在内。

    周期不由请求决定：回放始终用实例配置的周期，避免「实例按日线建、回放却按小时跑」
    这种对不上配置的结果。
    """

    start: UtcDatetime
    end: UtcDatetime


class StrategyReplayPoint(BaseModel):
    """回放曲线上的一个点：该时点的目标组合有几条腿、净敞口是多少。

    `as_of` 是**该根 K 线的开盘时刻**，不是决策时刻：回放在这个时点构造的视图包含
    这根已收盘的 K 线，因此它表达的是「这根 K 线收盘之后」的目标组合。下游不要把它
    当成「开盘前只知道历史」的时刻。

    净值需要资金与成本假设，属于回测；这里画的是目标组合本身的净敞口走势。
    """

    as_of: UtcDatetime
    net_exposure: DecimalString
    leg_count: int


_EXAMPLE_REPLAY_TARGET = {
    "legs": [
        {
            "inst_id": "XAAPL-USDT",
            "inst_type": "SPOT",
            "direction": "long",
            "target_weight": "0.5",
            "qty": None,
            "unit": None,
        },
        {
            "inst_id": "XMSFT-USDT",
            "inst_type": "SPOT",
            "direction": "short",
            "target_weight": "0.5",
            "qty": None,
            "unit": None,
        },
    ],
    "net_exposure": "0",
}

_EXAMPLE_REPLAY = {
    "replay_id": "srp_0001",
    "instance_id": "si_0001",
    "strategy_id": "relative_value",
    "bar": "1d",
    "start": "2026-10-10T00:00:00Z",
    "end": "2026-11-10T00:00:00Z",
    "target": _EXAMPLE_REPLAY_TARGET,
    "canonical_json": (
        '{"legs":[{"product_key":"AAPL","side":"long","target_weight":"0.5"},'
        '{"product_key":"MSFT","side":"short","target_weight":"0.5"}],'
        '"net_exposure":"0"}'
    ),
    "target_hash": "0f3c8c1a2b7d4e5f60718293a4b5c6d7e8f90123a4b5c6d7e8f90123a4b5c6d7",
    "points": [
        {"as_of": "2026-11-09T00:00:00Z", "net_exposure": "0.12", "leg_count": 2},
        {"as_of": "2026-11-10T00:00:00Z", "net_exposure": "0", "leg_count": 2},
    ],
    "created_at": "2026-11-10T09:30:00Z",
}


class StrategyReplay(BaseModel):
    """一次目标组合回放：目标组合 + 逐点净敞口 + 可复现的规范化 JSON 与哈希。

    `target` 用 `TargetPortfolio` 的既有形状；`canonical_json` 是它的规范化序列化
    （腿按 `product_key` 排序、键排序、无多余空白），`target_hash` 是这段文本的
    sha256——同一历史区间回放两次，两者都相同。
    """

    replay_id: str
    instance_id: str
    strategy_id: str
    bar: Bar
    start: UtcDatetime
    end: UtcDatetime
    target: TargetPortfolio
    canonical_json: str
    target_hash: str
    points: list[StrategyReplayPoint]
    created_at: UtcDatetime

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_REPLAY]})


class StrategyReplayListResponse(BaseModel):
    items: list[StrategyReplay]
    total: int

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [_EXAMPLE_REPLAY], "total": 1}]}
    )

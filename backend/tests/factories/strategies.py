"""策略实例的测试夹具：走域层写入路径，不依赖已删除的旧 HTTP 接口。

审批、组合与回测仍以 `strategy_instances` 为内部配置，但 v6 不再暴露实例 CRUD。
这些用例需要一个实例时，直接调用 `app.strategy.create_instance`，与生产域层同一条
校验与落库路径。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.strategy import (
    InstanceRecord,
    StrategyRecord,
    create_instance,
    create_strategy,
    update_instance,
)

__all__ = ["make_instance", "make_strategy", "patch_instance"]


def make_strategy(
    *,
    name: str = "测试策略",
    category: str = "relative_value",
    description: str | None = None,
    bar: str = "1d",
    direction: str = "long_short",
    params: Mapping[str, object] | None = None,
    inst_ids: Sequence[str],
) -> StrategyRecord:
    """建一条带首版草稿的用户策略，供回测入口按版本标识使用。"""

    rule = {
        "timeframe": bar,
        "direction": direction,
        "entry": {"all": [{"left": "MA(20)", "op": ">", "right": "MA(60)"}]},
        "exit": {"any": [{"left": "MA(20)", "op": "<", "right": "MA(60)"}]},
    }
    return create_strategy(
        name=name,
        category=category,
        description=description,
        timeframe=bar,
        direction=direction,
        rule_json=rule,
        parameters=params,
        instrument_ids=inst_ids,
        cost_model=None,
        position_sizing=None,
        change_note="初始版本",
    )


def make_instance(
    *,
    strategy_id: str = "relative_value",
    name: str = "测试实例",
    bar: str = "1d",
    params: Mapping[str, object] | None = None,
    inst_ids: Sequence[str],
) -> InstanceRecord:
    return create_instance(
        strategy_id=strategy_id,
        name=name,
        bar=bar,
        params=params,
        inst_ids=inst_ids,
    )


def patch_instance(
    instance_id: str,
    *,
    params: Mapping[str, object] | None = None,
    enabled: bool | None = None,
) -> InstanceRecord | None:
    return update_instance(instance_id, params=params, enabled=enabled)

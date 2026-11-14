"""策略实例的测试夹具：走域层写入路径，不依赖已删除的旧 HTTP 接口。

审批、组合与回测仍以 `strategy_instances` 为内部配置，但 v6 不再暴露实例 CRUD。
这些用例需要一个实例时，直接调用 `app.strategy.create_instance`，与生产域层同一条
校验与落库路径。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.strategy import InstanceRecord, create_instance, update_instance

__all__ = ["make_instance", "patch_instance"]


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

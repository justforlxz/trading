"""策略域端点：模板目录、实例增删改查与启停、目标组合回放。

端点只做入参校验与响应组装：模板投影、实例持久化与回放计算都在 `app.strategy` 里。
域层用 `None` 表示「没有这条实例」，这一层再翻译成 404；停用实例的回放由域层抛
`Conflict`，统一错误处理翻成 409，不会静默返回空结果。

审批相关端点不在这里：阶段推进只经 `/api/approvals` 的状态机（T3.6）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.mapping import decimal_str
from app.api.schemas import (
    ParamSpec,
    StrategyCatalogResponse,
    StrategyDefinition,
    StrategyInstance,
    StrategyInstanceCreateRequest,
    StrategyInstanceListResponse,
    StrategyInstanceUpdateRequest,
    StrategyReplay,
    StrategyReplayListResponse,
    StrategyReplayPoint,
    StrategyReplayRequest,
    TargetLeg,
    TargetPortfolio,
)
from app.strategy import (
    InstanceRecord,
    ReplayRecord,
    TemplateDefinition,
    create_instance,
    delete_instance,
    get_instance,
    list_instances,
    list_replays,
    prepare_replay,
    project_templates,
    save_replay,
    update_instance,
)

__all__ = ["strategy_router"]

strategy_router = APIRouter(tags=["strategy"])


@strategy_router.get("/strategies", response_model=StrategyCatalogResponse)
def list_strategy_templates() -> StrategyCatalogResponse:
    """模板目录：内容来自代码注册表，同时把它投影进 `strategy_templates` 表。

    `required_indicators` 与 `emitted_actions` 按空列表返回：模板只产出目标组合，
    既不引用指标模块的序列，也不产出单标的动作。
    """

    return StrategyCatalogResponse(items=[_definition(item) for item in project_templates()])


@strategy_router.get("/strategy-instances", response_model=StrategyInstanceListResponse)
def list_strategy_instances(
    strategy_id: str | None = Query(None),
    enabled: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> StrategyInstanceListResponse:
    """按模板与启停状态过滤的实例列表；`total` 是过滤条件下的全部条数。"""

    records, total = list_instances(strategy_id=strategy_id, enabled=enabled, limit=limit)
    return StrategyInstanceListResponse(
        items=[_instance(record) for record in records], total=total
    )


@strategy_router.post("/strategy-instances", response_model=StrategyInstance, status_code=201)
def create_strategy_instance(payload: StrategyInstanceCreateRequest) -> StrategyInstance:
    """建实例：模板必须已登记、参数必须过模板 schema、标的必须已同步。"""

    return _instance(
        create_instance(
            strategy_id=payload.strategy_id,
            name=payload.name,
            bar=payload.bar,
            params=payload.params,
            inst_ids=payload.inst_ids,
        )
    )


@strategy_router.get("/strategy-instances/{instance_id}", response_model=StrategyInstance)
def get_strategy_instance(instance_id: str) -> StrategyInstance:
    record = get_instance(instance_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到策略实例 {instance_id}")
    return _instance(record)


@strategy_router.patch("/strategy-instances/{instance_id}", response_model=StrategyInstance)
def update_strategy_instance(
    instance_id: str, payload: StrategyInstanceUpdateRequest
) -> StrategyInstance:
    """改参、换标的、启停；生命周期阶段不在这条端点上改。"""

    record = update_instance(
        instance_id,
        name=payload.name,
        params=payload.params,
        inst_ids=payload.inst_ids,
        enabled=payload.enabled,
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到策略实例 {instance_id}")
    return _instance(record)


@strategy_router.delete("/strategy-instances/{instance_id}", status_code=204, response_model=None)
def delete_strategy_instance(instance_id: str) -> None:
    """删除实例及其回放记录。"""

    if not delete_instance(instance_id):
        raise HTTPException(status_code=404, detail=f"未找到策略实例 {instance_id}")


@strategy_router.post(
    "/strategy-instances/{instance_id}/replays",
    response_model=StrategyReplay,
    status_code=201,
)
def create_strategy_replay(instance_id: str, payload: StrategyReplayRequest) -> StrategyReplay:
    """在历史区间上回放该实例的目标组合并落库。

    停用的实例返回 409（域层的 `Conflict`）：空结果与「没有信号」分不清。

    顺序是「算好 → 映射成契约模型 → 落库」：契约校验失败时库里不会多出一行读不出来
    的记录，历史接口也不会被一条坏行永久打坏。
    """

    record = prepare_replay(instance_id, start=payload.start, end=payload.end)
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到策略实例 {instance_id}")
    replay = _replay(record)
    save_replay(record)
    return replay


@strategy_router.get(
    "/strategy-instances/{instance_id}/replays",
    response_model=StrategyReplayListResponse,
)
def list_strategy_replays(
    instance_id: str,
    limit: int = Query(50, ge=1, le=200),
) -> StrategyReplayListResponse:
    """该实例已落库的回放记录；实例不存在返回 404，还没回放过返回空列表。"""

    result = list_replays(instance_id, limit=limit)
    if result is None:
        raise HTTPException(status_code=404, detail=f"未找到策略实例 {instance_id}")
    records, total = result
    return StrategyReplayListResponse(items=[_replay(record) for record in records], total=total)


def _definition(record: TemplateDefinition) -> StrategyDefinition:
    return StrategyDefinition(
        strategy_id=record.strategy_id,
        name=record.name,
        version=record.version,
        summary=record.summary,
        params=[
            ParamSpec(
                name=param.name,
                title=param.title,
                kind=param.kind,
                default=param.default,
                minimum=param.minimum,
                maximum=param.maximum,
            )
            for param in record.params
        ],
        required_indicators=[],
        required_bars=list(record.bars),
        emitted_actions=[],
    )


def _instance(record: InstanceRecord) -> StrategyInstance:
    return StrategyInstance(
        instance_id=record.instance_id,
        strategy_id=record.strategy_id,
        strategy_version=record.strategy_version,
        name=record.name,
        bar=record.bar,
        params=dict(record.params),
        inst_ids=list(record.inst_ids),
        status=record.lifecycle_status,
        enabled=record.enabled,
        execution_mode=record.execution_mode,
        latest_signal_at=record.latest_signal_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _replay(record: ReplayRecord) -> StrategyReplay:
    """域回放记录 → 契约模型：目标组合复用 `TargetPortfolio` 的既有形状。"""

    return StrategyReplay(
        replay_id=record.replay_id,
        instance_id=record.instance_id,
        strategy_id=record.strategy_id,
        bar=record.bar,
        start=record.start,
        end=record.end,
        target=TargetPortfolio(
            legs=[
                TargetLeg(
                    inst_id=leg.inst_id,
                    inst_type=leg.inst_type,
                    direction=leg.side,
                    target_weight=decimal_str(leg.target_weight),
                )
                for leg in record.legs
            ],
            net_exposure=decimal_str(record.net_exposure),
        ),
        canonical_json=record.canonical_json,
        target_hash=record.target_hash,
        points=[
            StrategyReplayPoint(
                as_of=point.as_of,
                net_exposure=decimal_str(point.net_exposure),
                leg_count=point.leg_count,
            )
            for point in record.points
        ],
        created_at=record.created_at,
    )

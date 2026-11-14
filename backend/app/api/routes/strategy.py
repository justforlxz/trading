"""v6 策略端点：用户策略、不可变版本、版本标的与回测关联。

端点只做参数校验与响应组装；规则校验、版本递增和事务边界都在 `app.strategy`。
旧模板目录与 `/api/strategy-instances` CRUD 已删除，不保留别名或双写；执行引擎与
审批状态机仍留在后端，但不由这里暴露。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query

from app.api.mapping import decimal_str
from app.api.schemas import (
    InstrumentStrategy,
    InstrumentStrategyListResponse,
    StrategyBacktestSummary,
    StrategyCreatedResponse,
    StrategyCreateRequest,
    StrategyDetail,
    StrategyInstrumentUpdateRequest,
    StrategyListResponse,
    StrategySummary,
    StrategyUpdatedResponse,
    StrategyUpdateRequest,
    StrategyVersionCreateRequest,
    StrategyVersionDetail,
    StrategyVersionListResponse,
    StrategyVersionSummary,
)
from app.backtest import BacktestRunHeader, latest_linked_backtests
from app.strategy import (
    InstrumentStrategyRecord,
    StrategyRecord,
    StrategyVersionRecord,
    create_strategy,
    create_version,
    get_user_strategy,
    get_version,
    list_strategies_for_instrument,
    list_user_strategies,
    list_versions,
    replace_version_instruments,
    update_strategy,
)

__all__ = ["strategy_router"]

strategy_router = APIRouter(tags=["strategy"])
_HUNDRED = Decimal(100)


@strategy_router.get("/strategies", response_model=StrategyListResponse)
def list_strategies_endpoint(
    status: str | None = Query(None),
    category: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None),
) -> StrategyListResponse:
    """用户策略列表：当前版本、状态、标的数量与最近回测摘要。"""

    records, next_cursor = list_user_strategies(
        status=status,
        category=category,
        limit=limit,
        cursor=cursor,
    )
    summaries = latest_linked_backtests(
        [version_id for record in records for version_id in record.version_ids]
    )
    return StrategyListResponse(
        items=[_summary(record, summaries) for record in records],
        next_cursor=next_cursor,
    )


@strategy_router.post("/strategies", response_model=StrategyCreatedResponse, status_code=201)
def create_strategy_endpoint(payload: StrategyCreateRequest) -> StrategyCreatedResponse:
    """创建策略与第一个草稿版本。"""

    record = create_strategy(
        name=payload.name,
        category=payload.category,
        description=payload.description,
        timeframe=payload.timeframe,
        direction=payload.direction,
        rule_json=payload.rule_json,
        parameters=payload.parameters,
        instrument_ids=payload.instrument_ids,
        cost_model=payload.cost_model,
        position_sizing=payload.position_sizing,
        change_note=payload.change_note,
    )
    return StrategyCreatedResponse(
        id=record.id,
        version_id=record.current_version_id,
        status=record.status,
        created_at=record.created_at,
    )


@strategy_router.get("/strategies/{strategy_id}", response_model=StrategyDetail)
def get_strategy_endpoint(strategy_id: str) -> StrategyDetail:
    """策略详情：当前版本、参数、标的、版本目录与最近回测。"""

    record = get_user_strategy(strategy_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到策略 {strategy_id}")
    versions = list_versions(strategy_id) or ()
    summaries = latest_linked_backtests(list(record.version_ids))
    return _detail(record, versions, summaries)


@strategy_router.put("/strategies/{strategy_id}", response_model=StrategyUpdatedResponse)
def update_strategy_endpoint(
    strategy_id: str, payload: StrategyUpdateRequest
) -> StrategyUpdatedResponse:
    """只改元数据时原地更新；提交任一版本字段时新建下一版。"""

    record = update_strategy(strategy_id, payload.model_dump(exclude_unset=True))
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到策略 {strategy_id}")
    return StrategyUpdatedResponse(
        id=record.id,
        version_id=record.current_version_id,
        status=record.status,
        updated_at=record.updated_at,
    )


@strategy_router.get(
    "/strategies/{strategy_id}/versions", response_model=StrategyVersionListResponse
)
def list_strategy_versions(strategy_id: str) -> StrategyVersionListResponse:
    versions = list_versions(strategy_id)
    if versions is None:
        raise HTTPException(status_code=404, detail=f"未找到策略 {strategy_id}")
    return StrategyVersionListResponse(
        items=[_version_detail(version) for version in versions],
        total=len(versions),
    )


@strategy_router.post(
    "/strategies/{strategy_id}/versions",
    response_model=StrategyVersionDetail,
    status_code=201,
)
def create_strategy_version(
    strategy_id: str, payload: StrategyVersionCreateRequest
) -> StrategyVersionDetail:
    """新建下一版；未提交的字段沿用当前版本。旧版本不提供修改入口。"""

    record = create_version(strategy_id, payload.model_dump(exclude_unset=True))
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到策略 {strategy_id}")
    version = get_version(strategy_id, record.current_version)
    if version is None:
        raise HTTPException(status_code=404, detail=f"未找到策略版本 {record.current_version}")
    return _version_detail(version)


@strategy_router.put(
    "/strategies/{strategy_id}/versions/{version}/instruments",
    response_model=StrategyVersionDetail,
)
def update_strategy_version_instruments(
    strategy_id: str,
    version: int,
    payload: StrategyInstrumentUpdateRequest,
) -> StrategyVersionDetail:
    """整批替换当前版本的标的集合；旧版本返回 409。"""

    record = replace_version_instruments(strategy_id, version, payload.instrument_ids)
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到策略 {strategy_id} 的版本 {version}")
    return _version_detail(record)


def _summary(record: StrategyRecord, summaries: dict[str, BacktestRunHeader]) -> StrategySummary:
    return StrategySummary(
        id=record.id,
        name=record.name,
        category=record.category,
        description=record.description,
        status=record.status,
        current_version_id=record.current_version_id,
        current_version=record.current_version,
        timeframe=record.timeframe,
        direction=record.direction,
        instrument_count=len(record.instrument_ids),
        latest_backtest=_latest_backtest(record, summaries),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _detail(
    record: StrategyRecord,
    versions: tuple[StrategyVersionRecord, ...],
    summaries: dict[str, BacktestRunHeader],
) -> StrategyDetail:
    return StrategyDetail(
        id=record.id,
        name=record.name,
        category=record.category,
        description=record.description,
        status=record.status,
        current_version_id=record.current_version_id,
        current_version=record.current_version,
        timeframe=record.timeframe,
        direction=record.direction,
        rule_json=dict(record.rule_json),
        parameters=dict(record.parameters),
        position_sizing=(None if record.position_sizing is None else dict(record.position_sizing)),
        cost_model=None if record.cost_model is None else dict(record.cost_model),
        instrument_ids=list(record.instrument_ids),
        versions=[
            StrategyVersionSummary(
                version_id=version.version_id,
                version=version.version,
                timeframe=version.timeframe,
                direction=version.direction,
                change_note=version.change_note,
                created_at=version.created_at,
            )
            for version in versions
        ],
        latest_backtest=_latest_backtest(record, summaries),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _version_detail(version: StrategyVersionRecord) -> StrategyVersionDetail:
    return StrategyVersionDetail(
        version_id=version.version_id,
        strategy_id=version.strategy_id,
        version=version.version,
        timeframe=version.timeframe,
        direction=version.direction,
        rule_json=dict(version.rule_json),
        parameters=dict(version.parameters),
        position_sizing=(
            None if version.position_sizing is None else dict(version.position_sizing)
        ),
        cost_model=None if version.cost_model is None else dict(version.cost_model),
        change_note=version.change_note,
        instrument_ids=list(version.instrument_ids),
        created_at=version.created_at,
    )


def _latest_backtest(
    record: StrategyRecord, summaries: dict[str, BacktestRunHeader]
) -> StrategyBacktestSummary | None:
    candidates = [
        (summaries[version_id], version_id)
        for version_id in record.version_ids
        if version_id in summaries
    ]
    if not candidates:
        return None
    header, version_id = max(candidates, key=lambda item: (item[0].created_at, item[0].run_id))
    return _backtest_summary(header, version_id)


def _backtest_summary(header: BacktestRunHeader, version_id: str) -> StrategyBacktestSummary:
    return StrategyBacktestSummary(
        run_id=header.run_id,
        strategy_version_id=version_id,
        data_source=header.data_source,
        total_return_pct=decimal_str(header.metrics["total_return"] * _HUNDRED),
        max_drawdown_pct=decimal_str(header.metrics["max_drawdown"] * _HUNDRED),
        trade_count=int(header.metrics["trade_count"]),
        backtest_start_date=header.start_date,
        backtest_end_date=header.end_date,
        created_at=header.created_at,
    )


def _instrument_strategy(
    record: InstrumentStrategyRecord, summaries: dict[str, BacktestRunHeader]
) -> InstrumentStrategy:
    candidates = [
        (summaries[version_id], version_id)
        for version_id in record.version_ids
        if version_id in summaries
    ]
    recent = None
    if candidates:
        header, version_id = max(candidates, key=lambda item: (item[0].created_at, item[0].run_id))
        recent = _backtest_summary(header, version_id)
    strategy = record.strategy
    return InstrumentStrategy(
        strategy_id=strategy.id,
        name=strategy.name,
        category=strategy.category,
        status=strategy.status,
        current_version_id=strategy.current_version_id,
        current_version=strategy.current_version,
        timeframe=strategy.timeframe,
        direction=strategy.direction,
        instrument_ids=list(strategy.instrument_ids),
        linked_version_ids=list(record.version_ids),
        recent_backtest=recent,
        updated_at=strategy.updated_at,
    )


@strategy_router.get(
    "/instruments/{inst_id}/strategies", response_model=InstrumentStrategyListResponse
)
def list_instrument_strategies(inst_id: str) -> InstrumentStrategyListResponse:
    """标的详情页的关联策略：最近一个月内有回测的，带最近一次结果。"""

    records = list_strategies_for_instrument(inst_id)
    version_ids = [version_id for record in records for version_id in record.version_ids]
    summaries = latest_linked_backtests(
        version_ids,
        created_since=datetime.now(UTC).replace(microsecond=0) - timedelta(days=30),
    )
    return InstrumentStrategyListResponse(
        items=[_instrument_strategy(record, summaries) for record in records]
    )

"""系统健康与手动同步端点。

健康检查只读已有事实，不在请求里临时探测上游；`okx_ws` 的状态由应用生命周期里的
`StreamHub` 提供。手动同步同步执行并写 `data_sync_jobs`，单进程部署没有独立 worker，
因此不在后台留下无法观察的任务。

同步只保留 OKX 公共行情的 `instruments` 与 `candles`，用于补齐全新部署时标的表与
K 线表为空的问题。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.schemas import (
    SystemComponent,
    SystemHealthResponse,
    SystemSyncRequest,
    SystemSyncResponse,
)
from app.core import Conflict, ValidationError
from app.jobs import (
    CANDLES_DATASET,
    DEFAULT_CANDLE_BAR,
    DEFAULT_CANDLE_DAYS,
    INSTRUMENTS_DATASET,
    OKX_PROVIDER,
    SYNC_DATASETS,
    run_candle_sync,
    run_instrument_sync,
)
from app.market import latest_sync_job, system_health

__all__ = ["system_router"]

system_router = APIRouter(tags=["system"])


@system_router.get("/system/health", response_model=SystemHealthResponse)
def get_system_health(request: Request) -> SystemHealthResponse:
    """数据库、OKX REST、OKX WebSocket、任务队列、K 线覆盖与宏观调度。"""

    hub: Any = getattr(request.app.state, "stream_hub", None)
    ws_status = hub.status_snapshot() if hub is not None else None
    # 宏观调度器与推送层同样是装配层挂在 app.state 上的组件；健康只读它记下的事实。
    scheduler: Any = getattr(request.app.state, "market_data_scheduler", None)
    macro_status = scheduler.status_snapshot() if scheduler is not None else None
    health = system_health(ws_status=ws_status, macro_status=macro_status)
    return SystemHealthResponse(
        status=health.status,
        checked_at=health.checked_at,
        components=[
            SystemComponent(
                name=item.name,
                status=item.status,
                last_success_at=item.last_success_at,
                error=item.error,
                detail=item.detail,
            )
            for item in health.components
        ],
    )


@system_router.post("/system/sync", response_model=SystemSyncResponse, status_code=202)
def post_system_sync(payload: SystemSyncRequest) -> SystemSyncResponse:
    """手动触发一次 OKX 数据同步；同一数据集已在运行时返回 409。"""

    dataset = payload.dataset.strip()
    if dataset not in SYNC_DATASETS:
        raise ValidationError(f"未知数据集 {dataset!r}; 支持: {', '.join(SYNC_DATASETS)}")
    return _sync_okx(dataset, payload)


def _sync_okx(dataset: str, payload: SystemSyncRequest) -> SystemSyncResponse:
    """OKX 公共行情的两个数据集：标的与历史 K 线。"""

    if dataset != CANDLES_DATASET and (payload.bar is not None or payload.days is not None):
        raise ValidationError(f"{dataset} 同步不接受 bar 或 days")

    before = latest_sync_job(provider=OKX_PROVIDER, dataset=dataset)
    if before is not None and before.status == "running":
        raise Conflict(f"OKX 的 {dataset} 同步任务仍在运行")

    try:
        if dataset == INSTRUMENTS_DATASET:
            job = run_instrument_sync()
        else:
            job = run_candle_sync(
                payload.instrument_ids,
                bar=payload.bar or DEFAULT_CANDLE_BAR,
                days=payload.days or DEFAULT_CANDLE_DAYS,
            )
    except Exception as exc:
        failed = latest_sync_job(provider=OKX_PROVIDER, dataset=dataset)
        if failed is None or (before is not None and failed.id == before.id):
            raise
        return SystemSyncResponse(
            job_id=failed.id,
            status=failed.status,
            rows=failed.rows,
            error=failed.error or f"{type(exc).__name__}: {exc}",
        )
    return SystemSyncResponse(
        job_id=job.id,
        status=job.status,
        rows=job.rows,
        error=job.error,
    )

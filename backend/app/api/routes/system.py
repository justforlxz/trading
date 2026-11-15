"""系统健康与手动同步端点。

健康检查只读已有事实，不在请求里临时探测上游；`okx_ws` 的状态由应用生命周期里的
`StreamHub` 提供。手动同步同步执行并写 `data_sync_jobs`，单进程部署没有独立 worker，
因此不在后台留下无法观察的任务。

`instruments` 与 `candles` 走 OKX 公共行情，补齐全新部署时标的表与 K 线表为空的问题；
`market_overview`、`market_events`、`news` 仍走设置里配置的外部行情 Provider。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.providers import configured_provider_name
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
from app.market import (
    DATASETS,
    get_provider,
    latest_sync_job,
    sync_external_dataset,
    system_health,
)

__all__ = ["system_router"]

system_router = APIRouter(tags=["system"])


def _provider_setting() -> tuple[str | None, str | None]:
    """读取设置里的 Provider 名；读取失败时把原因交给调用方，不伪装成「未配置」。"""

    try:
        return configured_provider_name(), None
    except Exception:
        # 数据库不可用时由健康接口如实报告，不在这里变成 500。
        return None, "读取设置表失败"


def _provider_name() -> str | None:
    return _provider_setting()[0]


@system_router.get("/system/health", response_model=SystemHealthResponse)
def get_system_health(request: Request) -> SystemHealthResponse:
    """数据库、OKX REST、OKX WebSocket、外部 Provider、任务队列与 K 线覆盖。"""

    hub: Any = getattr(request.app.state, "stream_hub", None)
    ws_status = hub.status_snapshot() if hub is not None else None
    provider_name, provider_error = _provider_setting()
    health = system_health(
        provider_name=provider_name,
        provider_error=provider_error,
        ws_status=ws_status,
    )
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
    """手动触发一次数据同步；同一 Provider 与数据集已在运行时返回 409。"""

    dataset = payload.dataset.strip()
    if dataset in SYNC_DATASETS:
        return _sync_okx(dataset, payload)
    if dataset not in DATASETS:
        supported = ", ".join((*SYNC_DATASETS, *DATASETS))
        raise ValidationError(f"未知数据集 {dataset!r}; 支持: {supported}")
    if payload.bar is not None or payload.days is not None:
        raise ValidationError(f"{dataset} 同步不接受 bar 或 days")
    return _sync_external(dataset, payload)


def _sync_okx(dataset: str, payload: SystemSyncRequest) -> SystemSyncResponse:
    """OKX 公共行情的两个数据集：标的与历史 K 线。"""

    provider = (payload.provider or "").strip()
    if provider and provider != OKX_PROVIDER:
        raise ValidationError(f"{dataset} 同步只支持 OKX, 实际 {provider!r}")
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


def _sync_external(dataset: str, payload: SystemSyncRequest) -> SystemSyncResponse:
    """外部行情 Provider 的三个数据集：沿用原有任务流水与失败返回方式。"""

    provider_name = (payload.provider or "").strip() or _provider_name()
    if provider_name is None:
        raise ValidationError("未配置外部行情 Provider")
    provider = get_provider(provider_name)
    assert provider is not None
    running = latest_sync_job(provider=provider_name, dataset=dataset)
    if running is not None and running.status == "running":
        raise Conflict(f"{provider_name} 的 {dataset} 同步任务仍在运行")
    try:
        job = sync_external_dataset(
            provider,
            dataset,
            instrument_ids=payload.instrument_ids,
        )
    except Exception as exc:
        failed = latest_sync_job(provider=provider_name, dataset=dataset)
        if failed is None:
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

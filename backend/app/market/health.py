"""系统健康读取：数据库、OKX REST、OKX WebSocket、外部 Provider、任务队列与 K 线覆盖。

健康接口只读已有事实，不在请求里临时探测上游：OKX REST 读同步任务或最近 K 线同步
时间，外部 Provider 读 `data_sync_jobs`，WebSocket 状态由推送层传入，任务队列读
`data_sync_jobs`，K 线覆盖读 `candles`。单项失败只影响该项，不阻断其他检查。

状态取值：

- `ok`：最近一次检查或同步成功；
- `stale`：有历史成功记录，但当前不可用或已过期；
- `error`：本次检查失败（例如数据库查询抛错）；
- `unconfigured`：从未配置或从未成功过。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.core import Clock, SystemClock
from app.db import session_scope
from app.market import sync_jobs
from app.market.external import MARKET_QUOTE_STALE_AFTER
from app.market.service import CandleCoverage, candle_coverage_summary

__all__ = [
    "COMPONENT_NAMES",
    "ComponentHealth",
    "SystemHealth",
    "system_health",
]

COMPONENT_NAMES: tuple[str, ...] = (
    "database",
    "okx_rest",
    "okx_ws",
    "external_provider",
    "job_queue",
    "candle_coverage",
)
OKX_PROVIDER = "okx"
CANDLE_STALE_AFTER = timedelta(days=3)
# 外部行情同步没有独立调度器，手动同步后一天内视为仍然新鲜。
MARKET_SYNC_STALE_AFTER = timedelta(hours=24)


def _window_label(window: timedelta) -> str:
    """新鲜度阈值 → 中文时长；两天以内按小时表达，避免文案与常量脱节。

    例如 24 小时写成「24 小时」而不是「1 天」，让文案与配置的阈值一一对应。
    """

    if window >= timedelta(days=2) and window % timedelta(days=1) == timedelta(0):
        return f"{window.days} 天"
    return f"{int(window.total_seconds() // 3600)} 小时"


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    name: str
    status: str
    last_success_at: datetime | None
    error: str | None
    detail: str | None


@dataclass(frozen=True, slots=True)
class SystemHealth:
    """一次健康检查的结果；`checked_at` 是本次检查时刻。"""

    status: str
    checked_at: datetime
    components: tuple[ComponentHealth, ...]


def _database(now: datetime) -> ComponentHealth:
    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        return ComponentHealth(
            name="database",
            status="error",
            last_success_at=None,
            error="数据库检查失败",
            detail=None,
        )
    return ComponentHealth(
        name="database",
        status="ok",
        last_success_at=now,
        error=None,
        detail=None,
    )


def _okx_rest(now: datetime, coverage: CandleCoverage) -> ComponentHealth:
    job = sync_jobs.latest_sync_job(provider=OKX_PROVIDER)
    if job is not None:
        last_success = sync_jobs.latest_success_at(provider=OKX_PROVIDER)
        if job.status == "failed":
            return ComponentHealth(
                name="okx_rest",
                status="stale",
                last_success_at=last_success,
                error=job.error,
                detail=f"{job.dataset} 最近一次同步失败",
            )
        if job.status == "running":
            return ComponentHealth(
                name="okx_rest",
                status="stale",
                last_success_at=last_success,
                error=None,
                detail=f"{job.dataset} 最近一次同步仍在运行",
            )
        if last_success is None or last_success < now - CANDLE_STALE_AFTER:
            return ComponentHealth(
                name="okx_rest",
                status="stale",
                last_success_at=last_success,
                error=None,
                detail=f"最近一次成功同步已超过 {_window_label(CANDLE_STALE_AFTER)}",
            )
        return ComponentHealth(
            name="okx_rest",
            status="ok",
            last_success_at=last_success,
            error=None,
            detail=f"{job.dataset} 最近一次同步成功且仍在时效内",
        )
    if coverage.last_synced_at is not None:
        if coverage.last_synced_at < now - CANDLE_STALE_AFTER:
            return ComponentHealth(
                name="okx_rest",
                status="stale",
                last_success_at=coverage.last_synced_at,
                error=None,
                detail=f"最近 K 线同步时间超过 {_window_label(CANDLE_STALE_AFTER)}",
            )
        return ComponentHealth(
            name="okx_rest",
            status="ok",
            last_success_at=coverage.last_synced_at,
            error=None,
            detail="来自 K 线同步记录",
        )
    return ComponentHealth(
        name="okx_rest",
        status="unconfigured",
        last_success_at=None,
        error=None,
        detail="尚无同步记录",
    )


def _parse_iso(value: object) -> datetime | None:
    """推送状态里的 ISO 字符串 → 带时区时间；无法解析时如实给 `None`。"""

    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _okx_ws(ws_status: Mapping[str, Any] | None) -> ComponentHealth:
    if not ws_status:
        return ComponentHealth(
            name="okx_ws",
            status="unconfigured",
            last_success_at=None,
            error=None,
            detail="推送层尚未启动",
        )
    connected = bool(ws_status.get("connected"))
    last_success = _parse_iso(ws_status.get("last_success_at"))
    error = ws_status.get("last_error")
    if connected:
        status = "ok"
    elif last_success is not None:
        status = "stale"
    else:
        status = "unconfigured"
    return ComponentHealth(
        name="okx_ws",
        status=status,
        last_success_at=last_success,
        error=None if error is None else "推送连接异常",
        detail=f"{ws_status.get('provider', 'okx')} / {ws_status.get('dataset', 'public_ws')}",
    )


def _external_provider(
    provider_name: str | None,
    now: datetime,
    provider_error: str | None = None,
) -> ComponentHealth:
    if provider_error is not None:
        return ComponentHealth(
            name="external_provider",
            status="error",
            last_success_at=None,
            error=provider_error,
            detail="无法读取外部行情 Provider 设置",
        )
    if provider_name is None:
        return ComponentHealth(
            name="external_provider",
            status="unconfigured",
            last_success_at=None,
            error=None,
            detail="未配置外部行情 Provider",
        )
    view = sync_jobs.provider_sync_status(
        provider_name,
        "market_overview",
        now=now,
        stale_after=MARKET_SYNC_STALE_AFTER,
    )
    quote_expired = view.data_as_of is not None and view.data_as_of < now - MARKET_QUOTE_STALE_AFTER
    if view.job_status == "running":
        detail = f"{provider_name} / market_overview 最近一次同步仍在运行"
    elif view.job_status == "failed":
        detail = f"{provider_name} / market_overview 最近一次同步失败"
    elif quote_expired:
        window = _window_label(MARKET_QUOTE_STALE_AFTER)
        detail = f"{provider_name} / market_overview 报价时间已超过 {window}"
    elif view.status == "ok":
        detail = f"{provider_name} / market_overview 最近一次同步成功且仍在时效内"
    elif view.status == "unconfigured":
        detail = f"{provider_name} / market_overview 尚未同步过"
    else:
        window = _window_label(MARKET_SYNC_STALE_AFTER)
        detail = f"{provider_name} / market_overview 数据已超过 {window}未更新"
    if view.failure_count:
        detail = f"{detail}；失败 {view.failure_count} 次"
    return ComponentHealth(
        name="external_provider",
        status="stale" if quote_expired else view.status,
        last_success_at=view.last_success_at,
        error=view.error,
        detail=detail,
    )


def _job_queue() -> ComponentHealth:
    view = sync_jobs.queue_sync_status()
    return ComponentHealth(
        name="job_queue",
        status=view.status,
        last_success_at=view.last_success_at,
        error=view.error,
        detail=f"运行中 {view.running}，超时 {view.stuck}，最近失败 {view.failed}",
    )


def _candle_coverage(now: datetime, coverage: CandleCoverage) -> ComponentHealth:
    detail = f"{coverage.candle_count} 根 K 线 / {coverage.symbol_count} 个标的"
    if coverage.candle_count == 0:
        return ComponentHealth(
            name="candle_coverage",
            status="unconfigured",
            last_success_at=None,
            error=None,
            detail=detail,
        )
    last_success = coverage.last_synced_at
    stale = last_success is not None and last_success < now - CANDLE_STALE_AFTER
    return ComponentHealth(
        name="candle_coverage",
        status="stale" if stale else "ok",
        last_success_at=last_success,
        error=None if not stale else "最近 K 线同步时间超过 3 天",
        detail=detail,
    )


def _safe(name: str, loader: Callable[[], ComponentHealth]) -> ComponentHealth:
    """单项检查失败只降级该项，不让整个健康响应变成 500。"""

    try:
        return loader()
    except Exception:
        return ComponentHealth(
            name=name,
            status="error",
            last_success_at=None,
            error="检查失败",
            detail=None,
        )


def _candle_component(
    now: datetime,
    coverage: CandleCoverage,
    error: str | None,
) -> ComponentHealth:
    if error is not None:
        return ComponentHealth(
            name="candle_coverage",
            status="error",
            last_success_at=None,
            error=error,
            detail=None,
        )
    return _candle_coverage(now, coverage)


def system_health(
    *,
    provider_name: str | None,
    provider_error: str | None = None,
    ws_status: Mapping[str, Any] | None = None,
    clock: Clock | None = None,
) -> SystemHealth:
    """执行一次健康检查；任何一项失败都只降级该项。"""

    now = (clock or SystemClock()).now().replace(microsecond=0)
    try:
        coverage = candle_coverage_summary()
        coverage_error = None
    except Exception:
        coverage = CandleCoverage(
            candle_count=0,
            symbol_count=0,
            latest_open_time=None,
            last_synced_at=None,
        )
        coverage_error = "K 线覆盖读取失败"
    components = (
        _database(now),
        _safe("okx_rest", lambda: _okx_rest(now, coverage)),
        _safe("okx_ws", lambda: _okx_ws(ws_status)),
        _safe(
            "external_provider",
            lambda: _external_provider(provider_name, now, provider_error),
        ),
        _safe("job_queue", _job_queue),
        _candle_component(now, coverage, coverage_error),
    )
    status = "ok" if all(item.status == "ok" for item in components) else "degraded"
    return SystemHealth(status=status, checked_at=now, components=components)

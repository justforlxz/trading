"""系统健康读取：数据库、OKX REST、OKX WebSocket、任务队列与 K 线覆盖。

健康接口只读已有事实，不在请求里临时探测上游：OKX REST 读同步任务或最近 K 线同步
时间，WebSocket 状态由推送层传入，任务队列读
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
    "job_queue",
    "candle_coverage",
    "macro",
)
OKX_PROVIDER = "okx"
CANDLE_STALE_AFTER = timedelta(days=3)
#: 宏观调度器每分钟一跳；一小时没有任何成功记录说明它已经停摆或持续失败。
MACRO_STALE_AFTER = timedelta(hours=1)


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
        detail=_ws_detail(ws_status),
    )


def _ws_detail(ws_status: Mapping[str, Any]) -> str:
    """连接身份 + 两路行情连接真实提交的订阅数量。

    超限跳过必须写出来：`fit_subscription` 在订阅请求装不下时按优先级截断，不静默
    丢弃；这里把跳过数量放进 `okx_ws` 的 detail，用户与验收都能直接读到。
    """

    detail = f"{ws_status.get('provider', 'okx')} / {ws_status.get('dataset', 'public_ws')}"
    detail += _subscriptions_text("", ws_status)
    candle = ws_status.get("candle")
    if isinstance(candle, Mapping):
        detail += _subscriptions_text("K 线", candle)
    return detail


def _subscriptions_text(label: str, block: Mapping[str, Any]) -> str:
    """`；K 线订阅 40 个标的，跳过 2 个（超限）`；没有订阅数量时不追加任何内容。"""

    subscriptions = block.get("subscriptions")
    if not isinstance(subscriptions, int):
        return ""
    text = f"；{label}订阅 {subscriptions} 个标的"
    skipped = block.get("skipped")
    if isinstance(skipped, int) and skipped > 0:
        text += f"，跳过 {skipped} 个（超限）"
    return text


def _macro(now: datetime, status: Mapping[str, Any] | None) -> ComponentHealth:
    """宏观调度器的最近状态；状态由 `app/jobs/market_data.py` 挂在 `app.state` 上。

    只读它已经记下的事实，不在这里探测上游，也不推断「上次成功」的时间。
    """

    if not status:
        return ComponentHealth(
            name="macro",
            status="unconfigured",
            last_success_at=None,
            error=None,
            detail="宏观调度器尚未启动",
        )
    last_success = _parse_iso(status.get("last_success_at"))
    error = status.get("last_error")
    error_text = None if not isinstance(error, str) or not error else error
    detail = _macro_detail(status)
    if status.get("degraded") or error_text is not None:
        return ComponentHealth(
            name="macro",
            status="error",
            last_success_at=last_success,
            error=error_text or "宏观同步连续失败",
            detail=detail,
        )
    if last_success is None:
        return ComponentHealth(
            name="macro",
            status="unconfigured",
            last_success_at=None,
            error=None,
            detail=detail or "宏观数据尚未同步",
        )
    if last_success < now - MACRO_STALE_AFTER:
        return ComponentHealth(
            name="macro",
            status="stale",
            last_success_at=last_success,
            error=None,
            detail=detail or f"超过 {_window_label(MACRO_STALE_AFTER)}未成功同步",
        )
    return ComponentHealth(
        name="macro",
        status="ok",
        last_success_at=last_success,
        error=None,
        detail=detail,
    )


def _macro_detail(status: Mapping[str, Any]) -> str:
    """`上次运行 …，下次 …，耗时 …ms；N 个源`：调度可观测性写在 detail 里。"""

    parts: list[str] = []
    last_run = _parse_iso(status.get("last_run_at"))
    next_run = _parse_iso(status.get("next_run_at"))
    if last_run is not None:
        parts.append(f"上次运行 {last_run.isoformat().replace('+00:00', 'Z')}")
    if next_run is not None:
        parts.append(f"下次 {next_run.isoformat().replace('+00:00', 'Z')}")
    duration = status.get("duration_ms")
    if isinstance(duration, int):
        parts.append(f"耗时 {duration}ms")
    series = status.get("series")
    if isinstance(series, list) and series:
        failed = sum(1 for item in series if isinstance(item, Mapping) and item.get("last_error"))
        degraded = sum(1 for item in series if isinstance(item, Mapping) and item.get("degraded"))
        parts.append(f"{len(series)} 个源，{failed} 个失败，{degraded} 个降级")
    return "，".join(parts)


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
    ws_status: Mapping[str, Any] | None = None,
    macro_status: Mapping[str, Any] | None = None,
    clock: Clock | None = None,
) -> SystemHealth:
    """执行一次健康检查；任何一项失败都只降级该项。

    `macro_status` 由装配层从调度器读来（与 `ws_status` 同一做法）：`app/market` 不
    import `app/macro`，避免两个业务包互相依赖。
    """

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
        _safe("job_queue", _job_queue),
        _candle_component(now, coverage, coverage_error),
        _safe("macro", lambda: _macro(now, macro_status)),
    )
    status = "ok" if all(item.status == "ok" for item in components) else "degraded"
    return SystemHealth(status=status, checked_at=now, components=components)

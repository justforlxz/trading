"""宏观观测的读取、抓取与降级。

三个边界分工明确：

- `macro_overview()` **只读库**，任何时候都不发起上游请求；上游失败时返回上次落库的
  值并标 `stale`，不用假数据填充，也不返回 500。
- 抓取有两条入口：调度器的一个 tick（`app/jobs/market_data.py`）与手动
  `POST /api/macro/sync`；两者都调用 `sync()`，按「序列 + 粒度」加锁，同一单元正在
  跑时其余调用立即跳过并记一行日志。
- 落库走 `app/macro/pipeline.py` 的中间件链：`enrich` 按 `ts` 算交易日与时段，
  `upsert` 按唯一键幂等写入。

利差只用**同一结算日**的两个国债日线结算值计算（`spread()`）；分钟级 10Y 单独展示，
不参与利差——它混着 15 分钟延迟与前一交易日结算，不是真实的期限利差。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.core import Clock, DataUnavailable, SystemClock, UpstreamError, ValidationError
from app.macro.config import MacroConfig, SeriesUnit, resolve_config
from app.macro.pipeline import PendingBatch, build_pipeline
from app.macro.providers import build_provider, source_url
from app.macro.runtime import MacroRuntime
from app.macro.series import GRANULARITY_DAILY, SERIES
from app.macro.store import (
    StoredObservation,
    has_trading_day,
    latest_ts,
    recent_map,
)
from app.market import from_epoch, last_settled_trading_day, settlement_epoch
from app.settings import load_settings

__all__ = [
    "MacroOverview",
    "SeriesReading",
    "SpreadReading",
    "SyncResult",
    "macro_overview",
    "reset_runtime",
    "runtime",
    "sync",
    "vix_regime",
]

logger = logging.getLogger(__name__)

# VIX 分级阈值：<15 低波 / 15–20 常态 / 20–30 偏高 / >30 恐慌。
REGIME_LOW = "low"
REGIME_NORMAL = "normal"
REGIME_ELEVATED = "elevated"
REGIME_PANIC = "panic"
_LOW_VOL_MAX = Decimal("15")
_ELEVATED_MAX = Decimal("20")
_PANIC_MIN = Decimal("30")

_RUNTIME = MacroRuntime()
#: 并发的多个手动刷新合并成一批：同一时刻只让一批请求上游，其余整批返回跳过。
_COALESCE_LOCK = threading.Lock()
_PIPELINE = build_pipeline()


@dataclass(frozen=True, slots=True)
class SeriesReading:
    """一个序列在一个粒度上的当前读数。"""

    series_id: str
    name: str
    unit: str
    granularity: str
    provider: str
    source_url: str | None
    value: Decimal | None
    change: Decimal | None
    as_of: datetime | None
    is_delayed: bool
    market_session: str | None
    quality_status: str
    regime: str | None
    error: str | None


@dataclass(frozen=True, slots=True)
class MacroSource:
    """一个来源：provider 名与它的上游地址。"""

    provider: str
    source_url: str | None


@dataclass(frozen=True, slots=True)
class SpreadReading:
    """2Y→10Y 利差；只由同一结算日的两个日线结算值算出。"""

    available: bool
    value_bp: Decimal | None
    inverted: bool
    trading_day: date | None
    quality_status: str
    reason: str | None
    #: 配对用的两个日线来源（按 provider + 地址去重）；默认配置下两者都是财政部，
    #: 合成一条。来源是配置事实，与这次配对有没有数据无关，所以不可用时也给。
    sources: tuple[MacroSource, ...]


@dataclass(frozen=True, slots=True)
class MacroOverview:
    as_of: datetime
    stale: bool
    stale_reason: str | None
    readings: tuple[SeriesReading, ...]
    spread: SpreadReading


@dataclass(frozen=True, slots=True)
class SyncResult:
    series_id: str
    granularity: str
    provider: str
    status: str
    rows: int
    error: str | None


def runtime() -> MacroRuntime:
    """进程内共享的同步状态；调度器与健康组件读同一份。"""

    return _RUNTIME


def reset_runtime() -> None:
    """清空同步状态；测试在用例之间调用。"""

    _RUNTIME.reset()


def vix_regime(value: Decimal) -> str:
    """VIX 分级：`<15` 低波、`15–20` 常态、`20–30` 偏高、`>30` 恐慌。

    边界取左闭右开，`30` 仍算偏高、超过 30 才是恐慌，与产品口径一致。
    """

    if value < _LOW_VOL_MAX:
        return REGIME_LOW
    if value < _ELEVATED_MAX:
        return REGIME_NORMAL
    if value <= _PANIC_MIN:
        return REGIME_ELEVATED
    return REGIME_PANIC


def _reading(
    *,
    series_id: str,
    name: str,
    unit: str,
    granularity: str,
    provider: str,
    source_url_value: str | None,
    points: Sequence[StoredObservation],
    stale: bool,
    error: str | None,
) -> SeriesReading:
    point = points[0] if points else None
    if point is None:
        return SeriesReading(
            series_id=series_id,
            name=name,
            unit=unit,
            granularity=granularity,
            provider=provider,
            source_url=source_url_value,
            value=None,
            change=None,
            as_of=None,
            is_delayed=False,
            market_session=None,
            quality_status="missing",
            regime=None,
            error=error or "尚未同步",
        )
    # 第二个点是上一个交易日的末条观测：日变化拿它比，不跨交易日找。
    previous = points[1] if len(points) > 1 else None
    change = None if previous is None else point.value - previous.value
    regime = vix_regime(point.value) if series_id == "vix" else None
    return SeriesReading(
        series_id=series_id,
        name=name,
        unit=unit,
        granularity=granularity,
        provider=provider,
        source_url=source_url_value,
        value=point.value,
        change=change,
        as_of=from_epoch(point.ts),
        is_delayed=point.is_delayed,
        market_session=point.market_session,
        quality_status="stale" if stale else "normal",
        regime=regime,
        error=None,
    )


def _is_settlement(point: StoredObservation) -> bool:
    """这条观测是不是真正的日结值：时刻等于该交易日收盘，且没有延迟标记。"""

    return not point.is_delayed and point.ts == settlement_epoch(point.trading_day)


def _spread(
    config: MacroConfig,
    latest: Mapping[tuple[str, str], StoredObservation],
    now: datetime,
) -> SpreadReading:
    """2Y→10Y 利差：只接受同一结算日的两个日线结算值。

    来源在这里解析一次并随结果返回，调用方不再重复查同样的两个 provider。另设一道
    防线：即使配置被改坏（日结槽填了分钟级源），只要某一腿不是真正的结算值，利差直接
    不可用——绝不用分钟级读数冒充日结，凑一个「看起来正常」的差值出来。
    """

    sources: list[MacroSource] = []
    latest_points: dict[str, StoredObservation | None] = {}
    for series_id, label in (("us10y", "10Y"), ("us2y", "2Y")):
        provider = config.provider_for(series_id, GRANULARITY_DAILY)
        source = MacroSource(
            provider=provider,
            source_url=_source_url_for(config, provider, series_id, now),
        )
        if source not in sources:
            sources.append(source)
        latest_points[label] = latest.get((series_id, provider))
    spread_sources = tuple(sources)

    ten = latest_points["10Y"]
    two = latest_points["2Y"]
    if two is None or ten is None:
        missing = [label for label, point in (("2Y", two), ("10Y", ten)) if point is None]
        return SpreadReading(
            available=False,
            value_bp=None,
            inverted=False,
            trading_day=None,
            quality_status="missing",
            reason=f"缺少 {' 与 '.join(missing)} 的日线结算值",
            sources=spread_sources,
        )
    for label, point in (("10Y", ten), ("2Y", two)):
        if not _is_settlement(point):
            return SpreadReading(
                available=False,
                value_bp=None,
                inverted=False,
                trading_day=None,
                quality_status="missing",
                reason=f"{label} 的最近一条不是日结值（来源与粒度不匹配），不用它计算利差",
                sources=spread_sources,
            )
    if ten.trading_day != two.trading_day:
        return SpreadReading(
            available=False,
            value_bp=None,
            inverted=False,
            trading_day=None,
            quality_status="missing",
            reason=(
                f"2Y 结算日 {two.trading_day.isoformat()} 与 10Y 结算日 "
                f"{ten.trading_day.isoformat()} 不同, 无法配对"
            ),
            sources=spread_sources,
        )
    value_bp = ((ten.value - two.value) * 100).normalize()
    return SpreadReading(
        available=True,
        value_bp=value_bp,
        inverted=value_bp < 0,
        trading_day=ten.trading_day,
        quality_status="normal",
        reason=None,
        sources=spread_sources,
    )


def macro_overview(*, clock: Clock | None = None) -> MacroOverview:
    """读库组装首页与关注列表要的读数；不发起任何上游请求。"""

    now = (clock or SystemClock()).now()
    config = resolve_config(load_settings().data_sources)
    units = config.units()
    recent = recent_map((unit.series_id, unit.provider) for unit in units)
    latest = {key: points[0] for key, points in recent.items() if points}
    stale, failure = _RUNTIME.staleness()

    readings: list[SeriesReading] = []
    for spec in SERIES:
        for granularity in spec.granularities:
            provider = config.provider_for(spec.series_id, granularity)
            readings.append(
                _reading(
                    series_id=spec.series_id,
                    name=spec.name,
                    unit=spec.unit,
                    granularity=granularity,
                    provider=provider,
                    # 来源地址跟着这一行的 provider 走：同一序列的分钟级与日结值来自
                    # 不同上游，共用一个地址会把链接指到另一个源。
                    source_url_value=_source_url_for(config, provider, spec.series_id, now),
                    points=recent.get((spec.series_id, provider), ()),
                    stale=stale,
                    error=failure,
                )
            )

    spread = _spread(config, latest, now)
    has_values = any(item.value is not None for item in readings)
    if not has_values:
        stale = True
        failure = failure or "宏观数据尚未同步"
    return MacroOverview(
        as_of=now,
        stale=stale,
        stale_reason=failure,
        readings=tuple(readings),
        spread=spread,
    )


def _source_url_for(
    config: MacroConfig, provider: str, series_id: str, now: datetime
) -> str | None:
    """这一行对应 provider 的上游地址；`{year}` 用当前年份替换。"""

    url = source_url(config.options(provider), series_id)
    return url.replace("{year}", str(now.year)) if url else None


def sync(
    *,
    units: Sequence[SeriesUnit] | None = None,
    respect_backoff: bool = False,
    skip_settled_daily: bool = False,
    coalesce: bool = False,
    clock: Clock | None = None,
) -> tuple[SyncResult, ...]:
    """按单元抓取并落库；同一单元正在运行或处于退避窗口时跳过。

    `respect_backoff` 只由调度器打开：手动刷新是用户的明确意图，不该被退避挡住，
    但仍然遵守单元锁——手动刷新不能让同一源并发打两次。
    `skip_settled_daily` 也由调度器打开：日线结算源在同一个交易日只会有一行，该日已经
    有观测就不再请求上游，这是调度器「每分钟跑一次」与「日更数据」之间的桥。
    `coalesce` 由手动刷新入口打开：两个用户动作同时到达时只让一批打上游，其余整批
    返回 `skipped` 并各记一行日志，不排队也不重复请求。
    """

    now = (clock or SystemClock()).now()
    config = resolve_config(load_settings().data_sources)
    targets = tuple(units) if units is not None else config.units()
    settled = last_settled_trading_day(now) if skip_settled_daily else None
    if coalesce and not _COALESCE_LOCK.acquire(blocking=False):
        logger.info("宏观同步跳过（已有另一批手动刷新在进行）: %d 个单元", len(targets))
        return tuple(_result(unit, "skipped", 0, None) for unit in targets)
    try:
        return _sync_units(targets, config, now, respect_backoff, settled)
    finally:
        if coalesce:
            _COALESCE_LOCK.release()


def _sync_units(
    targets: Sequence[SeriesUnit],
    config: MacroConfig,
    now: datetime,
    respect_backoff: bool,
    settled: date | None,
) -> tuple[SyncResult, ...]:
    """逐个单元抓取；每个单元单独加锁，已在跑或已在退避窗口内就跳过。"""

    results: list[SyncResult] = []
    for unit in targets:
        if (
            settled is not None
            and unit.granularity == GRANULARITY_DAILY
            and has_trading_day(unit.series_id, unit.provider, settled)
        ):
            logger.info(
                "宏观日线已存在，跳过上游请求: series=%s provider=%s trading_day=%s",
                unit.series_id,
                unit.provider,
                settled.isoformat(),
            )
            results.append(_result(unit, "unchanged", 0, None))
            continue
        if respect_backoff and _RUNTIME.in_backoff(unit, now):
            logger.info(
                "宏观同步跳过（退避中）: series=%s granularity=%s provider=%s",
                unit.series_id,
                unit.granularity,
                unit.provider,
            )
            results.append(_result(unit, "skipped", 0, None))
            continue
        if not _RUNTIME.acquire(unit):
            logger.info(
                "宏观同步跳过（正在运行）: series=%s granularity=%s provider=%s",
                unit.series_id,
                unit.granularity,
                unit.provider,
            )
            results.append(_result(unit, "skipped", 0, None))
            continue
        started = time.monotonic()
        try:
            rows = _sync_unit(unit, config, now)
        except (UpstreamError, DataUnavailable, ValidationError) as exc:
            _RUNTIME.record_failure(
                unit,
                now,
                interval_seconds=config.interval_seconds,
                message=str(exc),
            )
            logger.warning(
                "宏观同步失败: series=%s granularity=%s provider=%s: %s",
                unit.series_id,
                unit.granularity,
                unit.provider,
                exc,
            )
            results.append(_result(unit, "failed", 0, str(exc)))
        else:
            _RUNTIME.record_success(unit, now)
            logger.info(
                "宏观同步完成: series=%s granularity=%s provider=%s rows=%d 耗时=%dms",
                unit.series_id,
                unit.granularity,
                unit.provider,
                rows,
                int((time.monotonic() - started) * 1000),
            )
            results.append(_result(unit, "synced", rows, None))
        finally:
            _RUNTIME.release(unit)
    return tuple(results)


def _result(unit: SeriesUnit, status: str, rows: int, error: str | None) -> SyncResult:
    return SyncResult(
        series_id=unit.series_id,
        granularity=unit.granularity,
        provider=unit.provider,
        status=status,
        rows=rows,
        error=error,
    )


def _sync_unit(unit: SeriesUnit, config: MacroConfig, now: datetime) -> int:
    """抓一个单元并落库；返回写入的行数。"""

    provider = build_provider(unit.provider, options=config.options(unit.provider))
    if not provider.supports([unit.series_id]):
        raise ValidationError(f"provider {unit.provider} 不支持序列 {unit.series_id}")
    latest = latest_ts(unit.series_id, unit.provider)
    since = None if latest is None else datetime.fromtimestamp(latest, tz=now.tzinfo)
    observations = provider.fetch([unit.series_id], since)
    foreign = [item.provider for item in observations if item.provider != unit.provider]
    if foreign:
        raise ValidationError(
            f"provider {unit.provider} 返回了别的来源的行: {sorted(set(foreign))}"
        )
    outcome = _PIPELINE.run(PendingBatch(observations=tuple(observations)))
    if not outcome.completed:
        # 管道吞异常是它对「不拖垮调度器」的承诺，但落库没成立必须让上层记成失败，
        # 否则这里会回报 synced 与 N 行、健康组件显示 ok，实际库里一行都没有。
        raise DataUnavailable(f"宏观数据落库失败: {outcome.error}")
    return outcome.written

"""美股 K 线的抓取入口与只读总览。

三个边界分工明确：

- `equity_overview()` **只读库**，任何时候都不发起上游请求；上游失败时返回上次落库的
  值并标 `stale`，不用假数据填充，也不返回 500。
- 抓取有两个入口：调度器的一个 tick（`app/jobs/market_data.py`）与设置页的保存动作
  （保存后下一轮 tick 生效）。两者都调用 `sync()`，同一时刻只允许一批请求上游，
  其余立即跳过并记一行日志。
- 落库走 `app/equity/pipeline.py` 的中间件链：`enrich` 按 `open_time` 算交易时段，
  `upsert` 按唯一键幂等写入 `candles`，`publish` 把每根 K 线交给事件总线。

**延迟与时段如实标注**：Yahoo 免费源是 15 分钟级延迟行情、Stooq 是收盘后的日结数据，
两者都不是实时——`is_delayed` 由 provider 的声明决定，不用「看起来快」猜；`market_session`
取落库时按真实时刻算出的那一列。要真实时只能接付费源（provider 抽象已支持，本单不做）。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.core import Clock, DataUnavailable, SystemClock, UpstreamError, ValidationError
from app.equity.config import DAILY_BAR, EquityConfig, resolve_config
from app.equity.pipeline import PendingBatch, build_pipeline
from app.equity.providers import build_provider, provider_delayed, provider_url
from app.equity.runtime import EquityRuntime
from app.equity.store import StoredBar, latest_bars
from app.market import (
    US_EQUITY,
    asset_session,
    from_epoch,
    settlement_epoch,
    trading_day_of,
)
from app.settings import load_settings
from app.shared import bar_seconds

__all__ = [
    "EQUITY_STALE_AFTER",
    "LOOKBACK_BY_BAR",
    "SYMBOL_NAMES",
    "EquityOverview",
    "EquityReading",
    "SyncResult",
    "equity_overview",
    "reset_runtime",
    "runtime",
    "sync",
]

logger = logging.getLogger(__name__)

#: 抓取窗口的回看长度：分钟级取 7 天、日线取 120 天。
#:
#: 分钟级不能只回看 1 天：Yahoo 的 `range=1d` 给的是**最近一个交易日**的分钟线，周末与
#: 周一一早运行时，「最近 24 小时」整个落在休市区间里，会把上一个交易日的行情全部过滤掉
#: （实测：周日 15:48 UTC 跑一次，窗口变成周六 15:48 → 周日 15:48，结果 0 根）。
#: 回看一周既能跨过周末与休市日，也不会把整段历史算进一次 tick——上游本来就只给有限窗口。
#: 日线要覆盖 20 周期 ATR 的基线再加停牌与假日余量，120 个自然日足够（Yahoo 的上游窗口
#: 是 3 个月，这里只是本地过滤器，不能比上游窗口更短）。
LOOKBACK_BY_BAR: dict[str, timedelta] = {
    "1m": timedelta(days=7),
    "1d": timedelta(days=120),
}
DEFAULT_LOOKBACK = timedelta(days=1)

#: 最近一根 K 线的收盘时刻超过这个阈值就算过期：渠道停摆（进程没起、上游长期失败）。
#: 取 3 天是为了跨过周末——周五收盘到周一开盘约 2.7 天，不该被判成过期。
EQUITY_STALE_AFTER = timedelta(days=3)

#: 标的的展示名；未登记的标的直接用代码，不编造名称。
SYMBOL_NAMES: dict[str, str] = {
    "SPY": "标普 500 ETF",
    "QQQ": "纳斯达克 100 指数 ETF",
}

QUALITY_NORMAL = "normal"
QUALITY_DELAYED = "delayed"
QUALITY_STALE = "stale"
QUALITY_MISSING = "missing"

_RUNTIME = EquityRuntime()
_PIPELINE = build_pipeline()


@dataclass(frozen=True, slots=True)
class EquityReading:
    """一个美股标的的当前读数；`as_of` 是这根 K 线的收盘时刻。"""

    symbol: str
    name: str
    provider: str
    bar: str
    value: Decimal | None
    as_of: datetime | None
    market_session: str | None
    is_delayed: bool
    quality_status: str
    source_url: str | None


@dataclass(frozen=True, slots=True)
class EquityOverview:
    """首页「市场概况」里的美股区：逐行读数与顶层过期提示。"""

    as_of: datetime
    stale: bool
    stale_reason: str | None
    readings: tuple[EquityReading, ...]


@dataclass(frozen=True, slots=True)
class SyncResult:
    provider: str
    bar: str
    status: str
    rows: int
    published: int
    error: str | None


def runtime() -> EquityRuntime:
    """进程内共享的同步状态；调度器与健康组件读同一份。"""

    return _RUNTIME


def reset_runtime() -> None:
    """清空同步状态；测试在用例之间调用。"""

    _RUNTIME.reset()


def _close_time(item: StoredBar) -> datetime:
    """一根 K 线的**定稿时刻**，界面上的「数据时间」用它。

    - 分钟级：`open_time + 周期`。用 `open_time` 会把 15:59 那一分钟标成「数据时间
      15:59」，而它到 16:00 才定稿。
    - 日线：该交易日正常时段**收盘**（美东 16:00，`settlement_epoch`）。日线的
      `open_time` 已被对齐到当日 09:30 开盘（`app/market.session.daily_open_time`），
      再按周期加 24 小时会得到**次日 09:30**，收盘后到次日开盘前那段时间里它是一个
      未来时刻。
    """

    if item.bar == "1d":
        return from_epoch(settlement_epoch(trading_day_of(item.open_time)))
    return item.open_time + timedelta(seconds=bar_seconds(item.bar))


def _reading(
    *,
    symbol: str,
    config: EquityConfig,
    stored: StoredBar | None,
    now: datetime,
    is_delayed: bool,
    channel_failing: bool,
) -> EquityReading:
    source_url = provider_url(config.provider, symbol, config.bar)
    name = SYMBOL_NAMES.get(symbol, symbol)
    if stored is None:
        # 没有 K 线时这一行是「缺失」，但市场开没开仍然是事实：给当前时段，不给
        # 空字符串让界面显示「未知时段（）」。
        return EquityReading(
            symbol=symbol,
            name=name,
            provider=config.provider,
            bar=config.bar,
            value=None,
            as_of=None,
            market_session=asset_session(US_EQUITY, now),
            is_delayed=is_delayed,
            quality_status=QUALITY_MISSING,
            source_url=source_url,
        )
    as_of = _close_time(stored)
    if channel_failing:
        # 上游正在失败：库里的值只是上一次成功的结果，不能再当作可用数据。
        quality = QUALITY_STALE
    elif now - as_of > EQUITY_STALE_AFTER:
        quality = QUALITY_STALE
    elif is_delayed:
        quality = QUALITY_DELAYED
    else:
        quality = QUALITY_NORMAL
    return EquityReading(
        symbol=symbol,
        name=name,
        provider=config.provider,
        bar=config.bar,
        value=stored.close,
        as_of=as_of,
        market_session=stored.market_session or None,
        is_delayed=is_delayed,
        quality_status=quality,
        source_url=source_url,
    )


def equity_overview(*, clock: Clock | None = None) -> EquityOverview:
    """读库组装首页的美股读数；不发起任何上游请求，读库失败也不返回 500。"""

    now = (clock or SystemClock()).now()
    config = resolve_config(load_settings().data_sources)
    is_delayed = provider_delayed(config.provider)
    # 上游最近一次抓取是否失败：失败时库里的旧值仍然返回，但必须标成 stale。
    channel_failing, upstream_failure = _RUNTIME.staleness()
    try:
        stored = latest_bars(config.symbols, bar=config.bar, source=config.provider)
        read_failure = None
    except Exception as exc:  # 读库失败：降级为「缺失」，原因如实带出
        logger.exception("美股 K 线读取失败")
        stored = {}
        read_failure = f"读取美股 K 线失败: {exc}"

    readings = tuple(
        _reading(
            symbol=symbol,
            config=config,
            stored=stored.get(symbol),
            now=now,
            is_delayed=is_delayed,
            channel_failing=channel_failing,
        )
        for symbol in config.symbols
    )
    stale, reason = _staleness(readings, read_failure, upstream_failure)
    return EquityOverview(as_of=now, stale=stale, stale_reason=reason, readings=readings)


def _staleness(
    readings: tuple[EquityReading, ...],
    read_failure: str | None,
    upstream_failure: str | None,
) -> tuple[bool, str | None]:
    """顶层过期提示：读库失败、上游失败、缺数据、数据过期都算；正常时 `(False, None)`。

    上游失败即使库里有新鲜缓存值也要标：那些值只代表「上一次成功」，不是当前可用数据。
    原因带上游原始错误，首页与设置页的健康区因此说的是同一件事。
    """

    if read_failure is not None:
        return True, read_failure
    if upstream_failure is not None:
        return True, f"美股行情抓取失败：{upstream_failure}"
    missing = [item.symbol for item in readings if item.quality_status == QUALITY_MISSING]
    if missing:
        return True, f"尚未同步 {' / '.join(missing)} 的行情"
    stale = [item.symbol for item in readings if item.quality_status == QUALITY_STALE]
    if stale:
        hours = int(EQUITY_STALE_AFTER.total_seconds() // 3600)
        return True, f"{' / '.join(stale)} 最近一根 K 线已超过 {hours} 小时未更新"
    return False, None


def sync(
    *,
    respect_backoff: bool = False,
    clock: Clock | None = None,
) -> tuple[SyncResult, ...]:
    """抓一次美股行情并落库；同一时刻已有抓取在跑时跳过。

    `respect_backoff` 只由调度器打开：手动触发是用户的明确意图，不该被退避挡住，但仍然
    遵守单元锁——手动触发不能让同一源并发打两次。

    一个标的失败即整批记失败：上游一次请求返回一份标的清单，半份成功、半份失败时按
    「全部重试」处理比按标的拆开重试更不容易漏。下一轮 tick 会退避后重试。
    """

    now = (clock or SystemClock()).now()
    config = resolve_config(load_settings().data_sources)
    if respect_backoff and _RUNTIME.in_backoff(now):
        logger.info("美股同步跳过（退避中）: provider=%s", config.provider)
        return (_result(config, "skipped", 0, 0, None),)
    if not _RUNTIME.acquire():
        logger.info("美股同步跳过（正在运行）: provider=%s", config.provider)
        return (_result(config, "skipped", 0, 0, None),)

    started = time.monotonic()
    failures: list[str] = []
    try:
        results = tuple(_sync_batches(config, now, failures))
    finally:
        _RUNTIME.release()

    if failures:
        _RUNTIME.record_failure(now, interval_seconds=config.interval_seconds, message=failures[0])
        logger.warning("美股同步失败: provider=%s: %s", config.provider, failures[0])
    else:
        _RUNTIME.record_success(now)
    logger.info(
        "美股同步完成: provider=%s 耗时=%dms 结果=%s",
        config.provider,
        int((time.monotonic() - started) * 1000),
        ", ".join(f"{item.bar}={item.status}/{item.rows}" for item in results),
    )
    return results


def _batches(config: EquityConfig) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """这一轮要抓的（周期, 标的）批次。

    每个周期一批；日线那一批还要带上三个大盘指数——它们不在 `equity.symbols` 里（界面
    上不显示），但指数日线是 ATR 的唯一来源，由渠道固定维护。放在同一批是因为它们走
    同一条管道、同一个来源，「一个标的失败即整批记失败」对它们同样适用。
    """

    return tuple(
        (bar, config.daily_symbols if bar == DAILY_BAR else config.symbols) for bar in config.bars
    )


def _sync_batches(config: EquityConfig, now: datetime, failures: list[str]) -> list[SyncResult]:
    """逐个批次抓取；一批失败只记这批的失败，另一批仍然落库。"""

    results: list[SyncResult] = []
    for bar, symbols in _batches(config):
        try:
            outcome = _sync_once(config, bar, symbols, now)
        except (UpstreamError, DataUnavailable, ValidationError) as exc:
            failures.append(str(exc))
            results.append(
                SyncResult(
                    provider=config.provider,
                    bar=bar,
                    status="failed",
                    rows=0,
                    published=0,
                    error=str(exc),
                )
            )
            continue
        results.append(
            SyncResult(
                provider=config.provider,
                bar=bar,
                status="synced",
                rows=outcome.written,
                published=outcome.published,
                error=None,
            )
        )
    return results


def _sync_once(config: EquityConfig, bar: str, symbols: tuple[str, ...], now: datetime):
    """抓一个周期的窗口并交给管道；落库没成立时抛 `DataUnavailable`。"""

    provider = build_provider(config.provider, bar=bar, options=config.options(bar))
    if not provider.supports(symbols):
        raise ValidationError(f"provider {config.provider} 不支持标的 {list(symbols)}")
    start = now - LOOKBACK_BY_BAR.get(bar, DEFAULT_LOOKBACK)
    bars = provider.fetch(list(symbols), start, now)
    foreign = sorted({item.source for item in bars if item.source != config.provider})
    if foreign:
        raise ValidationError(f"provider {config.provider} 返回了别的来源的行: {foreign}")
    outcome = _PIPELINE.run(PendingBatch(bars=tuple(bars)))
    if not outcome.completed:
        # 管道吞异常是它对「不拖垮调度器」的承诺，但落库没成立必须让上层记成失败，
        # 否则这里会回报 synced 与 N 行、健康组件显示 ok，实际库里一行都没有。
        raise DataUnavailable(f"美股 K 线落库失败: {outcome.error}")
    return outcome


def _result(
    config: EquityConfig,
    status: str,
    rows: int,
    published: int,
    error: str | None,
) -> SyncResult:
    return SyncResult(
        provider=config.provider,
        bar=config.bar,
        status=status,
        rows=rows,
        published=published,
        error=error,
    )

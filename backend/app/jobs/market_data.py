"""市场数据的进程内定时调度器：本域**唯一**的定时来源（宏观 + 美股）。

一个 tick 周期（`settings.data_sources.macro.scheduler.minute` 与
`settings.data_sources.equity.scheduler.minute`，支持 `1m` / `5m`）依次做两件事：

1. **宏观**：分钟级序列每次都拉；日线结算序列按「上一个已结算美股交易日」判重，
   该日已有观测就跳过，不发上游请求。
2. **美股**：按配置的 provider 抓 1 个窗口（Yahoo 分钟级 / Stooq 日线），
   交给 `app/equity/pipeline.py` 的中间件链落 `candles`。

两个域各自记自己的状态：一个域的配置写坏或上游挂掉，不能让另一个域也停摆，因此
`_tick` 分别兜住异常，健康组件也分别读两份快照。

调度只决定「什么时候跑」；抓取、加锁、退避与落库都在各域的 `sync` 里。调度器持有
最近一次 tick 的时间与耗时，健康组件通过 `app.state` 读到它。

线程写法沿用 `app/jobs/equity.py` 的先例：守护线程等一个 `threading.Event`，停止事件
一到立即结束等待，应用退出不会留下悬挂线程。**启动后先等一个周期再跑第一次**，不在
启动瞬间制造一次上游请求——本地起服务与被测试装配时都不该顺带打外部接口。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Event, Thread
from typing import Any

from app.alerts import scan_market_alerts
from app.core import Clock, SystemClock
from app.equity import (
    EquityConfig,
)
from app.equity import (
    SyncResult as EquitySyncResult,
)
from app.equity import resolve_config as resolve_equity_config
from app.equity import runtime as equity_runtime
from app.equity import sync as equity_sync
from app.macro import GRANULARITY_DAILY, SyncResult, resolve_config, runtime, sync
from app.settings import load_settings

__all__ = ["MarketDataScheduler", "start_market_data_scheduler"]

logger = logging.getLogger(__name__)

#: 只有日线才能当 ATR 的来源：大盘与组合异动都由它驱动。
DAILY_BAR = "1d"
#: 停止时给正在跑的那一次 tick 的收尾时间。
STOP_TIMEOUT_SECONDS = 5.0
#: 配置读不出来时的等待秒数：一分钟，与默认周期一致。
FALLBACK_INTERVAL_SECONDS = 60


@dataclass(frozen=True, slots=True)
class _FixedClock:
    """把一个 tick 的时刻固定下来：退避与记录都用同一个时间，不跨时钟。"""

    moment: datetime

    def now(self) -> datetime:
        return self.moment


class MarketDataScheduler:
    """按配置周期抓宏观与美股数据；一个进程只起一条线程。"""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        """起守护线程；重复调用只保留一条线程。"""

        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = Thread(
            target=self._loop,
            name="trading-market-data",
            daemon=True,
        )
        self._thread.start()
        # 首次 tick 要等一个周期；先把「下次计划」登记下来，健康组件不必等到第一次
        # 运行才有可读的时间。
        moment = self._clock.now()
        runtime().plan_next(
            moment + timedelta(seconds=_interval_seconds(FALLBACK_INTERVAL_SECONDS))
        )
        equity_runtime().plan_next(
            moment + timedelta(seconds=_equity_interval_seconds(FALLBACK_INTERVAL_SECONDS))
        )

    def join(self, timeout: float = STOP_TIMEOUT_SECONDS) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    def shutdown(self, timeout: float = STOP_TIMEOUT_SECONDS) -> None:
        self._stop.set()
        self.join(timeout=timeout)

    def status_snapshot(self) -> dict[str, Any]:
        """健康组件读的宏观快照：最近一次运行的时间、下次计划与耗时，以及逐单元状态。"""

        return runtime().status()

    def equity_status_snapshot(self) -> dict[str, Any]:
        """健康组件读的美股快照：最近运行、下次计划、耗时与最近一次错误。"""

        return equity_runtime().status()

    def run_once(self, *, now: datetime | None = None) -> tuple[SyncResult, ...]:
        """执行一个宏观 tick；测试直接调用它，不依赖线程与等待。"""

        moment = now or self._clock.now()
        config = resolve_config(load_settings().data_sources)
        started = time.monotonic()
        results = sync(
            respect_backoff=True,
            skip_settled_daily=True,
            clock=_FixedClock(moment),
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        runtime().record_tick(
            now=moment,
            next_run_at=moment + timedelta(seconds=config.interval_seconds),
            duration_ms=duration_ms,
        )
        logger.info(
            "宏观调度 tick 完成: interval=%s 耗时=%dms 结果=%s",
            config.interval,
            duration_ms,
            ", ".join(f"{item.series_id}/{item.granularity}={item.status}" for item in results),
        )
        return results

    def run_equity_once(self, *, now: datetime | None = None) -> tuple[EquitySyncResult, ...]:
        """执行一个美股 tick；与宏观分开记状态，一个域失败不影响另一个。"""

        moment = now or self._clock.now()
        config: EquityConfig = resolve_equity_config(load_settings().data_sources)
        started = time.monotonic()
        results = equity_sync(respect_backoff=True, clock=_FixedClock(moment))
        duration_ms = int((time.monotonic() - started) * 1000)
        equity_runtime().record_tick(
            now=moment,
            next_run_at=moment + timedelta(seconds=config.interval_seconds),
            duration_ms=duration_ms,
        )
        logger.info(
            "美股调度 tick 完成: interval=%s provider=%s 耗时=%dms 结果=%s",
            config.interval,
            config.provider,
            duration_ms,
            ", ".join(f"{item.provider}/{item.bar}={item.status}" for item in results),
        )
        return results

    def run_market_alert_scan(self) -> None:
        """收盘数据落地后评估大盘与组合异动；失败只记日志，不拖累调度线程。

        不新增定时器：调用点就在已经存在的调度轮次里，且只在**这一轮真的收到新的收盘
        数据**时才调用，所以一天最多评估一次，不按分钟空转。
        """

        try:
            result = scan_market_alerts()
        except Exception:
            logger.exception("大盘/组合提醒扫描失败")
            return
        logger.info("大盘/组合提醒扫描完成: created=%d expired=%d", result.created, result.expired)

    def _loop(self) -> None:
        """等一个周期再跑一次；周期每轮重读，改配置后下一轮生效。"""

        while not self._stop.is_set():
            if self._stop.wait(_interval_seconds(FALLBACK_INTERVAL_SECONDS)):
                return
            self._tick()

    def _tick(self) -> None:
        """跑一个完整周期；两个域各自兜住异常，一个挂掉不拖累另一个。"""

        macro_results: tuple[SyncResult, ...] = ()
        equity_results: tuple[EquitySyncResult, ...] = ()
        try:
            macro_results = self.run_once()
        except Exception:
            logger.exception("宏观调度 tick 失败")
        try:
            equity_results = self.run_equity_once()
        except Exception:
            logger.exception("美股调度 tick 失败")
        if _settled(macro_results, equity_results):
            self.run_market_alert_scan()


def _settled(
    macro_results: tuple[SyncResult, ...],
    equity_results: tuple[EquitySyncResult, ...],
) -> bool:
    """这一轮是否收到了新的收盘数据：宏观的新日结值，或美股的新日线。

    调度周期是分钟级，但日线与日结值一天只变一次。没有新数据就不评估，避免每分钟
    读一遍指数与自选日线；有的数据源一轮里只更新一边，两边都看才不漏。
    """

    if any(item.rows > 0 and item.granularity == GRANULARITY_DAILY for item in macro_results):
        return True
    return any(item.bar == DAILY_BAR and item.published > 0 for item in equity_results)


def _interval_seconds(fallback: int) -> int:
    """当前配置的宏观 tick 周期；配置读不出来时按 `fallback` 等，不中断调度线程。"""

    try:
        return resolve_config(load_settings().data_sources).interval_seconds
    except Exception:
        logger.exception("宏观调度周期读取失败, 本轮按 %d 秒等待", fallback)
        return fallback


def _equity_interval_seconds(fallback: int) -> int:
    """当前配置的美股 tick 周期；配置读不出来时按 `fallback` 等。"""

    try:
        return resolve_equity_config(load_settings().data_sources).interval_seconds
    except Exception:
        logger.exception("美股调度周期读取失败, 本轮按 %d 秒等待", fallback)
        return fallback


def start_market_data_scheduler(*, clock: Clock | None = None) -> MarketDataScheduler:
    """创建并启动调度器；调用方负责在退出时 `shutdown()`。"""

    scheduler = MarketDataScheduler(clock=clock)
    scheduler.start()
    return scheduler

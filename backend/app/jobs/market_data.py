"""宏观数据的进程内定时调度器：本域**唯一**的定时来源。

一个 tick 周期（`settings.data_sources.macro.scheduler.minute`，支持 `1m` / `5m`）：

1. 分钟级序列每次都拉；
2. 日线结算序列按「上一个已结算美股交易日」判重，该日已有观测就跳过，不发上游请求。

调度只决定「什么时候跑」；抓取、加锁、退避与落库都在 `app.macro.sync` 里。调度器
持有最近一次 tick 的时间与耗时，健康组件通过 `app.state` 读到它。

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

from app.core import Clock, SystemClock
from app.macro import SyncResult, resolve_config, runtime, sync
from app.settings import load_settings

__all__ = ["MarketDataScheduler", "start_market_data_scheduler"]

logger = logging.getLogger(__name__)

#: 停止时给正在跑的那一次 tick 的收尾时间。
STOP_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class _FixedClock:
    """把一个 tick 的时刻固定下来：退避与记录都用同一个时间，不跨时钟。"""

    moment: datetime

    def now(self) -> datetime:
        return self.moment


class MarketDataScheduler:
    """按配置周期抓宏观数据；一个进程只起一条线程。"""

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
        runtime().plan_next(self._clock.now() + timedelta(seconds=_interval_seconds(60)))

    def join(self, timeout: float = STOP_TIMEOUT_SECONDS) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    def shutdown(self, timeout: float = STOP_TIMEOUT_SECONDS) -> None:
        self._stop.set()
        self.join(timeout=timeout)

    def status_snapshot(self) -> dict[str, Any]:
        """健康组件读的快照：最近一次运行的时间、下次计划与耗时，以及逐单元状态。"""

        return runtime().status()

    def run_once(self, *, now: datetime | None = None) -> tuple[SyncResult, ...]:
        """执行一个 tick；测试直接调用它，不依赖线程与等待。"""

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

    def _loop(self) -> None:
        """等一个周期再跑一次；周期每轮重读，改配置后下一轮生效。"""

        while not self._stop.is_set():
            interval = _interval_seconds(60)
            if self._stop.wait(interval):
                return
            try:
                self.run_once()
            except Exception:
                logger.exception("宏观调度 tick 失败")


def _interval_seconds(fallback: int) -> int:
    """当前配置的 tick 周期；配置读不出来时按 `fallback` 等，不中断调度线程。"""

    try:
        return resolve_config(load_settings().data_sources).interval_seconds
    except Exception:
        logger.exception("宏观调度周期读取失败, 本轮按 %d 秒等待", fallback)
        return fallback


def start_market_data_scheduler(*, clock: Clock | None = None) -> MarketDataScheduler:
    """创建并启动调度器；调用方负责在退出时 `shutdown()`。"""

    scheduler = MarketDataScheduler(clock=clock)
    scheduler.start()
    return scheduler

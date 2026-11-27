"""进程内任务装配：批量回测的标的集合、扫描计划与进程内队列。

单进程部署下没有独立 worker / 调度器 / 消息队列，定时与批量任务都跑在同一进程里。
本包只做装配：真源清单来自各域门面，调度与并发在本包里，业务计算留给各域。

- `queue`：有界并发的进程内队列，自己上报「同时处于 running 的峰值」，单个任务失败
  不拖垮整批；
- `scope`：把标的集合模式（单标的 / 手选 / Watchlist / 分组 / 全部可交易）解析成具体
  标的序列；
- `sweep`：标的 × 参数组合 × 三段区间展开成任务，交给队列跑完并装回扫描行；
- `on_demand`：用户进入某个标的时才同步对应周期，按「标的 + 周期」去重并限制并发；
- `candle_refresh`：有持仓与自选的标的哪个周期过期了就补一次，挂在已有的调度轮次里。
"""

from app.jobs.candle_refresh import (
    MAX_REFRESH_DAYS,
    SETTLE_GRACE,
    refresh_due,
    run_candle_refresh,
)
from app.jobs.equity import (
    next_beijing_midnight,
    start_equity_snapshot_scheduler,
)
from app.jobs.market_data import (
    MarketDataScheduler,
    start_market_data_scheduler,
)
from app.jobs.on_demand import (
    DEFAULT_DAYS_BY_BAR,
    WATCHLIST_BAR,
    WATCHLIST_DAYS,
    OnDemandSyncScheduler,
    SyncSubmission,
)
from app.jobs.queue import (
    DEFAULT_MAX_CONCURRENCY,
    QueueOutcome,
    QueueReport,
    run_tasks,
)
from app.jobs.scope import SCOPE_MODES, TargetScope, resolve_scope
from app.jobs.sweep import SweepOutcome, SweepPlan, plan_sweep, run_sweep
from app.jobs.sync import (
    CANDLES_DATASET,
    DEFAULT_CANDLE_BAR,
    DEFAULT_CANDLE_DAYS,
    INSTRUMENTS_DATASET,
    OKX_PROVIDER,
    SYNC_DATASETS,
    run_candle_sync,
    run_instrument_sync,
)

__all__ = [
    "CANDLES_DATASET",
    "DEFAULT_CANDLE_BAR",
    "DEFAULT_CANDLE_DAYS",
    "DEFAULT_DAYS_BY_BAR",
    "DEFAULT_MAX_CONCURRENCY",
    "INSTRUMENTS_DATASET",
    "MAX_REFRESH_DAYS",
    "OKX_PROVIDER",
    "SCOPE_MODES",
    "SETTLE_GRACE",
    "SYNC_DATASETS",
    "WATCHLIST_BAR",
    "WATCHLIST_DAYS",
    "MarketDataScheduler",
    "OnDemandSyncScheduler",
    "QueueOutcome",
    "QueueReport",
    "SweepOutcome",
    "SweepPlan",
    "SyncSubmission",
    "TargetScope",
    "next_beijing_midnight",
    "plan_sweep",
    "refresh_due",
    "resolve_scope",
    "run_candle_refresh",
    "run_candle_sync",
    "run_instrument_sync",
    "run_sweep",
    "run_tasks",
    "start_equity_snapshot_scheduler",
    "start_market_data_scheduler",
]

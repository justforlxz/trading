"""进程内任务装配：批量回测的标的集合、扫描计划与进程内队列。

单进程部署下没有独立 worker / 调度器 / 消息队列，定时与批量任务都跑在同一进程里。
本包只做装配：真源清单来自各域门面，调度与并发在本包里，业务计算留给各域。

- `queue`：有界并发的进程内队列，自己上报「同时处于 running 的峰值」，单个任务失败
  不拖垮整批；
- `scope`：把标的集合模式（单标的 / 手选 / Watchlist / 分组 / 全部可交易）解析成具体
  标的序列；
- `sweep`：标的 × 参数组合 × 三段区间展开成任务，交给队列跑完并装回扫描行。
"""

from app.jobs.equity import (
    next_beijing_midnight,
    start_equity_snapshot_scheduler,
)
from app.jobs.queue import (
    DEFAULT_MAX_CONCURRENCY,
    QueueOutcome,
    QueueReport,
    run_tasks,
)
from app.jobs.scope import SCOPE_MODES, TargetScope, resolve_scope
from app.jobs.sweep import SweepOutcome, SweepPlan, plan_sweep, run_sweep

__all__ = [
    "DEFAULT_MAX_CONCURRENCY",
    "SCOPE_MODES",
    "QueueOutcome",
    "QueueReport",
    "SweepOutcome",
    "SweepPlan",
    "TargetScope",
    "next_beijing_midnight",
    "plan_sweep",
    "resolve_scope",
    "run_sweep",
    "run_tasks",
    "start_equity_snapshot_scheduler",
]

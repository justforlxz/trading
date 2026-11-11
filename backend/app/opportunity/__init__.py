"""机会发现：把「哪些标的值得做、往哪个方向做」变成有记录、可回看的候选对象。

本包对外发布三类东西：

- 纯函数（`app.opportunity.detect`）—— 两种模式的评分与筛选，输入输出可直接断言；
- 编排入口（`detect_opportunities` / `list_opportunities` / `get_opportunity` /
  `set_status`）—— 负责取数、落库与事务边界；
- 状态机的唯一真源（`ALLOWED_TRANSITIONS` / `transition`）。

跨包调用一律走本门面，不允许 `from app.opportunity.detect import ...` 之类的子模块
直连。锚点只是分析起点：锚点自身没有方向时它不会出现在候选腿里。
"""

from app.opportunity.detect import (
    LEG_LIMIT,
    LONG,
    MIN_ABS_CORRELATION,
    MIN_RESONANCE,
    MIN_TREND,
    MODE_MARKET,
    MODE_TARGET,
    SHORT,
    WINDOW_BARS,
    Candidate,
    Leg,
    Observation,
    leg_of,
    market_candidates,
    target_candidate,
    trend,
)
from app.opportunity.service import (
    ALLOWED_TRANSITIONS,
    BAR,
    STATUSES,
    OpportunityRecord,
    detect_opportunities,
    get_opportunity,
    list_opportunities,
    set_status,
    transition,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "BAR",
    "LEG_LIMIT",
    "LONG",
    "MIN_ABS_CORRELATION",
    "MIN_RESONANCE",
    "MIN_TREND",
    "MODE_MARKET",
    "MODE_TARGET",
    "SHORT",
    "STATUSES",
    "WINDOW_BARS",
    "Candidate",
    "Leg",
    "Observation",
    "OpportunityRecord",
    "detect_opportunities",
    "get_opportunity",
    "leg_of",
    "list_opportunities",
    "market_candidates",
    "set_status",
    "target_candidate",
    "transition",
    "trend",
]

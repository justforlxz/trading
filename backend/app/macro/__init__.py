"""宏观数据域：provider 可切换、分钟级落库、按页面职责提供读数。

跨包只允许 `from app.macro import ...`，发布的都是装配层与测试真正用到的名字：

- `macro_overview`：读库组装首页与关注列表的读数，不发起上游请求；
- `sync`：抓取入口，调度器与手动刷新共用；按「序列 + 粒度」加锁；
- `resolve_config`：`settings.data_sources.macro` 的解析结果；
- `runtime`：进程内同步状态，健康组件与调度器共用。

序列清单、粒度常量与分级纯函数是包内实现细节，跨包用不到；测试按需要从子模块导入。

定时只在 `app/jobs/market_data.py`，本包内没有任何定时原语。
"""

from app.macro.config import resolve_config, validate_series_override
from app.macro.service import (
    MacroOverview,
    MacroSource,
    SeriesReading,
    SpreadReading,
    SyncResult,
    macro_overview,
    runtime,
    sync,
)

__all__ = [
    "MacroOverview",
    "MacroSource",
    "SeriesReading",
    "SpreadReading",
    "SyncResult",
    "macro_overview",
    "resolve_config",
    "runtime",
    "sync",
    "validate_series_override",
]

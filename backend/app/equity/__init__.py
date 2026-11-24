"""美股行情域：可切换的 provider、分钟级与日线落库、首页读数与健康状态。

跨包只允许 `from app.equity import ...`，发布的都是装配层与测试真正用到的名字：

- `equity_overview`：读库组装首页「市场概况」的美股读数，不发起上游请求；
- `sync`：抓取入口，调度器与设置页共用；同一时刻只允许一批请求上游；
- `resolve_config`：`settings.data_sources.equity` 的解析结果；
- `runtime` / `reset_runtime`：进程内同步状态，健康组件与调度器共用；
- `validate_equity_override`：设置写入时的 provider / 标的校验。

标的名进 `candles.symbol`，provider 名进 `candles.source`；本域不新建表，也不写
`instruments`——标的登记与交易规则属于标的域，本单只做行情渠道。

一个实现可以服务多个周期：Yahoo 同时维护分钟级与日线，日线额外带上三个大盘指数
（`app.market.indexes`），它是 ATR 与大盘异动的唯一来源。

定时只在 `app/jobs/market_data.py`，本包内没有任何定时原语。
"""

from app.equity.config import EquityConfig, resolve_config, validate_equity_override
from app.equity.service import (
    EquityReading,
    SyncResult,
    equity_overview,
    reset_runtime,
    runtime,
    sync,
)

__all__ = [
    "EquityConfig",
    "EquityReading",
    "SyncResult",
    "equity_overview",
    "reset_runtime",
    "resolve_config",
    "runtime",
    "sync",
    "validate_equity_override",
]

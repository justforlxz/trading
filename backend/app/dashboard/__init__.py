"""首页汇总：八个模块分别读取、分别降级。

门面即出口：跨包只允许 `from app.dashboard import ...`。
"""

from __future__ import annotations

from app.dashboard.service import (
    ActivityItem,
    AlertItem,
    DashboardSummary,
    MarketData,
    Module,
    PositionItem,
    PositionsData,
    RiskData,
    StrategiesData,
    WatchlistData,
    load_summary,
)

__all__ = [
    "ActivityItem",
    "AlertItem",
    "DashboardSummary",
    "MarketData",
    "Module",
    "PositionItem",
    "PositionsData",
    "RiskData",
    "StrategiesData",
    "WatchlistData",
    "load_summary",
]

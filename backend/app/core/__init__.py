"""跨模块公共层（冻结层）。

只放四类东西：错误体系、值对象、端口，以及端口需要的最小原语（注册表、时钟）。

本包必须是叶子：除自己以外不 import 任何 `app` 模块，也不碰数据库、网络与配置。
门禁见 `tests/architecture/test_core_is_leaf.py`——新增依赖前先想清楚它是否真的属于
「所有模块都需要且互不冲突」的那一类。
"""

from __future__ import annotations

from app.core.clock import Clock, ReplayClock, SystemClock, utc_from_millis
from app.core.errors import (
    Conflict,
    DataUnavailable,
    ExecutionRejected,
    InvariantViolation,
    RiskBlocked,
    TradingError,
    UpstreamError,
    ValidationError,
)
from app.core.ports import Fill, MarketDataPort, Order, Position, Ticker, TradePort
from app.core.registry import get, list_names, register
from app.core.types import Bar, InstrumentRef, Money, OrderIntent, Signal, Timeframe

__all__ = [
    "Bar",
    "Clock",
    "Conflict",
    "DataUnavailable",
    "ExecutionRejected",
    "Fill",
    "InstrumentRef",
    "InvariantViolation",
    "MarketDataPort",
    "Money",
    "Order",
    "OrderIntent",
    "Position",
    "ReplayClock",
    "RiskBlocked",
    "Signal",
    "SystemClock",
    "Ticker",
    "Timeframe",
    "TradePort",
    "TradingError",
    "UpstreamError",
    "ValidationError",
    "get",
    "list_names",
    "register",
    "utc_from_millis",
]

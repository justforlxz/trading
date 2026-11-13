"""交易历史（journal）：只读聚合。

本模块把策略配置、回测预期、模拟或实盘成交放在同一份视图里，供 Trades 页读取。
它不建自己的表，也不写任何表：所有条目都由已有事实派生。跨包只允许
`from app.journal import ...`。
"""

from __future__ import annotations

from app.journal.aggregate import build_journal, build_strategy_journal, realized_summary
from app.journal.model import ExecutionSnapshot, RecordedSignal
from app.journal.service import latest_expectations, load_journal

__all__ = [
    "ExecutionSnapshot",
    "RecordedSignal",
    "build_journal",
    "build_strategy_journal",
    "latest_expectations",
    "load_journal",
    "realized_summary",
]

"""助手只读端口。

`app.ai` 只能通过这个协议拿域数据：协议只描述**只读查询**，实现放在
`app.adapters.domain`，因此 `app.ai` 不需要、也不允许 import 任何业务域模块
（见 `docs/architecture/api-contract.md` §4 的 import 白名单）。

本文件只有 Protocol 与一个异常，不 import 任何域模块，也不含任何 IO。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol

# `AiReadsError.reason` 的闭集：前五个映射成 404，`no_data` 保持 200 数据不足语义。
REASONS: frozenset[str] = frozenset(
    {
        "target_not_found",
        "strategy_not_found",
        "backtest_not_found",
        "opportunity_not_found",
        "instrument_not_found",
        "no_data",
    }
)


class AiReadsError(Exception):
    """端口层的确定错误：`reason` 取 `REASONS` 中的一个。"""

    def __init__(self, reason: str, message: str = "") -> None:
        if reason not in REASONS:
            raise ValueError(f"unknown ai reads reason: {reason}")
        self.reason = reason
        self.message = message or reason
        super().__init__(self.message)


class AiReads(Protocol):
    """只读事实来源：每个方法只读不写，返回成型 dict / list。"""

    async def market_sessions(self, *, start: date, end: date) -> list[dict[str, Any]]: ...

    async def market_coverage(
        self,
        *,
        inst_ids: list[str] | None,
        bar: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        """返回 `{"instruments": [{"instrument_id", "inst_id"}], "coverage": [...]}`。"""
        ...

    async def target_list(self, *, limit: int) -> list[dict[str, Any]]: ...

    async def target_relations(self, *, target_id: int) -> dict[str, Any]:
        """返回 status/reason/snapshot/edges/significant_changes; 无快照时 snapshot=None。"""
        ...

    async def strategy_list(self, *, limit: int) -> list[dict[str, Any]]: ...

    async def strategy_detail(self, *, strategy_id: int) -> dict[str, Any]:
        """`{"strategy", "legs", "approval_count"}`。"""
        ...

    async def backtest_detail(self, *, run_id: int) -> dict[str, Any]:
        """`{"run", "metrics"}`。"""
        ...

    async def risk_status(self, *, strategy_id: int | None) -> dict[str, Any]: ...

    async def positions(self) -> dict[str, Any]:
        """`{"items": [...], "totals": {...}}`。"""
        ...

    async def opportunity_detail(self, *, opportunity_id: int) -> dict[str, Any]: ...


__all__ = ["REASONS", "AiReads", "AiReadsError"]

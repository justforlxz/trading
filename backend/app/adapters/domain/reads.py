"""`AiReads` 的域实现：只读编排各域 service，把结果整理成成型 dict。

约束:
- 只调用各域的**查询**函数, 不调 `sync_*` / `get_or_create_*` / 任何写接口;
- 域异常在这里统一转成 `AiReadsError(reason=...)`, 不外泄域错误类型;
- 返回值是纯 dict/list, `app.ai` 不需要 import 任何域模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.backtest import service as backtest_service
from app.backtest.errors import BacktestError
from app.config import get_settings
from app.db.session import AsyncSession
from app.execution import service as execution_service
from app.market import candles as candle_service
from app.market import instruments as instrument_service
from app.market import sessions as session_service
from app.market.models import Instrument
from app.opportunity.models import Opportunity
from app.ports.ai_reads import AiReadsError
from app.research import relations as relation_service
from app.research import targets as target_service
from app.risk import service as risk_service
from app.risk.errors import RiskError
from app.strategy import service as strategy_service
from app.strategy.core.constraints import ConstraintViolation

COVERAGE_LIMIT = 5


@dataclass(slots=True)
class DomainAiReads:
    """基于一次数据库会话的只读实现。"""

    session: AsyncSession
    _instrument_cache: dict[str, Instrument | None] = field(default_factory=dict)

    # ------------------------------------------------------------------ market

    async def market_sessions(self, *, start: date, end: date) -> list[dict[str, Any]]:
        # 只读既有日历; 窗口内没有数据就返回空列表, 由上层给「数据不足」。
        rows = await session_service.list_sessions(self.session, start=start, end=end)
        return [session_service.session_payload(row) for row in rows]

    async def market_coverage(
        self,
        *,
        inst_ids: list[str] | None,
        bar: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        instruments = await self._resolve_instruments(inst_ids)
        coverage = [
            await candle_service.coverage(
                self.session, instrument=instrument, bar=bar, start=start, end=end
            )
            for instrument in instruments[:COVERAGE_LIMIT]
        ]
        return {
            "instruments": [
                {"instrument_id": instrument.id, "inst_id": instrument.inst_id}
                for instrument in instruments
            ],
            "coverage": coverage,
        }

    async def _resolve_instruments(self, inst_ids: list[str] | None) -> list[Instrument]:
        if inst_ids:
            found = [
                instrument
                for instrument in [await self._instrument(inst_id) for inst_id in inst_ids]
                if instrument is not None
            ]
            if not found:
                raise AiReadsError("instrument_not_found", f"未知标的: {', '.join(inst_ids)}")
            return found
        targets, _ = await target_service.list_targets(self.session, enabled=True, limit=50)
        return [
            instrument
            for instrument in [
                await self._instrument_by_id(target.instrument_id)
                for target in targets
                if target.instrument_id is not None
            ]
            if instrument is not None
        ]

    # --------------------------------------------------------------- research

    async def target_list(self, *, limit: int) -> list[dict[str, Any]]:
        rows, _ = await target_service.list_targets(self.session, limit=limit)
        return [
            {
                "id": row.id,
                "symbol": row.symbol,
                "instrument_id": row.instrument_id,
                "enabled": row.enabled,
            }
            for row in rows
        ]

    async def target_relations(self, *, target_id: int) -> dict[str, Any]:
        if await target_service.get_target(self.session, target_id) is None:
            raise AiReadsError("target_not_found", f"目标股票 {target_id} 不存在")
        snapshot = await relation_service.latest_snapshot(self.session, target_id)
        if snapshot is None:
            return {
                "status": "undefined",
                "reason": None,
                "snapshot": None,
                "edges": [],
                "significant_changes": [],
            }
        payload = await relation_service.build_relations_payload(
            self.session, snapshot, threshold=get_settings().relation_change_threshold
        )
        edges = list(payload.get("edges") or [])
        for edge in edges:
            instrument = await self._instrument(edge.get("counterparty_inst_id"))
            edge["instrument_id"] = instrument.id if instrument is not None else None
        return {
            "status": payload.get("status"),
            "reason": payload.get("reason"),
            "snapshot": payload.get("snapshot"),
            "edges": edges,
            "significant_changes": list(payload.get("significant_changes") or []),
        }

    # --------------------------------------------------------------- strategy

    async def strategy_list(self, *, limit: int) -> list[dict[str, Any]]:
        rows, _ = await strategy_service.list_strategies(self.session, limit=limit)
        return [
            {
                "id": row.id,
                "name": row.name,
                "kind": row.kind,
                "status": row.status,
                "version": row.version,
            }
            for row in rows
        ]

    async def strategy_detail(self, *, strategy_id: int) -> dict[str, Any]:
        try:
            strategy = await strategy_service.get_strategy(self.session, strategy_id)
            legs = await strategy_service.load_legs(self.session, strategy_id)
            approvals = await strategy_service.load_approvals(self.session, strategy_id)
        except ConstraintViolation as exc:
            raise AiReadsError("strategy_not_found", exc.message) from exc
        return {
            "strategy": {
                "id": strategy.id,
                "name": strategy.name,
                "kind": strategy.kind,
                "status": strategy.status,
                "version": strategy.version,
            },
            "legs": [
                {
                    "instrument_id": leg.instrument_id,
                    "inst_id": inst_id,
                    "side": leg.side,
                    "target_weight": str(leg.target_weight),
                    "rationale": leg.rationale,
                    "rank": leg.rank,
                }
                for leg, inst_id, _uly in legs
            ],
            "approval_count": len(approvals),
        }

    # --------------------------------------------------------------- backtest

    async def backtest_detail(self, *, run_id: int) -> dict[str, Any]:
        try:
            run = await backtest_service.get_run(self.session, run_id)
            metrics = await backtest_service.load_metrics(self.session, run_id)
        except BacktestError as exc:
            reason = "backtest_not_found" if exc.status_code == 404 else "no_data"
            raise AiReadsError(reason, exc.message) from exc
        return {
            "run": {
                "id": run.id,
                "strategy_id": run.strategy_id,
                "status": run.status,
                "bar": run.bar,
                "initial_capital": str(run.initial_capital),
                "window": {
                    "start": _iso(run.window_start),
                    "end": _iso(run.window_end),
                },
            },
            "metrics": [
                {"name": row.name, "value": str(row.value), "unit": row.unit} for row in metrics
            ],
        }

    # ------------------------------------------------------- risk / positions

    async def risk_status(self, *, strategy_id: int | None) -> dict[str, Any]:
        try:
            return await risk_service.status(self.session, strategy_id=strategy_id)
        except RiskError as exc:
            reason = "strategy_not_found" if exc.status_code == 404 else "no_data"
            raise AiReadsError(reason, exc.message) from exc

    async def positions(self) -> dict[str, Any]:
        return await execution_service.positions_view(self.session)

    # ---------------------------------------------------------- opportunity

    async def opportunity_detail(self, *, opportunity_id: int) -> dict[str, Any]:
        opportunity = await self.session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise AiReadsError("opportunity_not_found", f"机会 {opportunity_id} 不存在")
        instrument = await self._instrument_by_id(opportunity.primary_instrument_id)
        if instrument is None:
            raise AiReadsError(
                "instrument_not_found",
                f"机会 {opportunity_id} 的标的 {opportunity.primary_instrument_id} 不存在",
            )
        return {
            "id": opportunity.id,
            "kind": opportunity.kind,
            "direction": opportunity.direction,
            "score": str(opportunity.score),
            "reasons": list(opportunity.reasons or []),
            "instrument_id": instrument.id,
            "inst_id": instrument.inst_id,
        }

    # ---------------------------------------------------------------- helpers

    async def _instrument(self, inst_id: str | None) -> Instrument | None:
        if not inst_id:
            return None
        if inst_id not in self._instrument_cache:
            self._instrument_cache[inst_id] = await instrument_service.get_instrument(
                self.session, inst_id
            )
        return self._instrument_cache[inst_id]

    async def _instrument_by_id(self, instrument_id: int | None) -> Instrument | None:
        if instrument_id is None:
            return None
        return await self.session.get(Instrument, instrument_id)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


__all__ = ["COVERAGE_LIMIT", "DomainAiReads"]

"""风控的只读数据访问。

风控可以只读 ``strategy`` / ``market`` / ``backtest`` 三个 schema 的数据，
但这些模块不反向依赖风控。这里只做查询与轻量映射，不做任何业务计算。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.models import BacktestEquityPoint, BacktestRun
from app.market.models import Candle, Instrument
from app.strategy.models import Strategy, StrategyLeg


@dataclass(frozen=True, slots=True)
class StrategySource:
    id: int
    name: str
    kind: str
    status: str
    version: int
    content_hash: str | None


@dataclass(frozen=True, slots=True)
class StrategyLegSpec:
    instrument_id: int
    inst_id: str
    symbol: str
    side: str
    target_weight: Decimal
    rank: int | None


@dataclass(frozen=True, slots=True)
class BacktestBaseline:
    id: int
    initial_capital: Decimal


@dataclass(frozen=True, slots=True)
class EquityPoint:
    ts: datetime
    equity: Decimal
    drawdown: Decimal


async def load_strategy(session: AsyncSession, strategy_id: int) -> StrategySource | None:
    row = await session.get(Strategy, strategy_id)
    if row is None:
        return None
    return StrategySource(
        id=row.id,
        name=row.name,
        kind=row.kind,
        status=row.status,
        version=row.version,
        content_hash=row.content_hash,
    )


async def list_approved_strategies(session: AsyncSession) -> tuple[int, ...]:
    stmt = select(Strategy.id).where(Strategy.status == "approved").order_by(Strategy.id)
    return tuple((await session.execute(stmt)).scalars().all())


async def load_legs(session: AsyncSession, strategy_id: int) -> tuple[StrategyLegSpec, ...]:
    stmt = (
        select(StrategyLeg, Instrument)
        .join(Instrument, Instrument.id == StrategyLeg.instrument_id)
        .where(StrategyLeg.strategy_id == strategy_id)
        .order_by(StrategyLeg.rank, StrategyLeg.id)
    )
    rows = (await session.execute(stmt)).all()
    return tuple(
        StrategyLegSpec(
            instrument_id=leg.instrument_id,
            inst_id=instrument.inst_id,
            symbol=instrument.uly or instrument.inst_id,
            side=leg.side,
            target_weight=leg.target_weight,
            rank=leg.rank,
        )
        for leg, instrument in rows
    )


async def latest_backtest_run(session: AsyncSession, strategy_id: int) -> BacktestBaseline | None:
    stmt = (
        select(BacktestRun)
        .where(BacktestRun.strategy_id == strategy_id, BacktestRun.status == "ok")
        .order_by(BacktestRun.id.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    return BacktestBaseline(id=row.id, initial_capital=Decimal(row.initial_capital))


async def load_equity_series(session: AsyncSession, run_id: int) -> tuple[EquityPoint, ...]:
    stmt = (
        select(BacktestEquityPoint.ts, BacktestEquityPoint.equity, BacktestEquityPoint.drawdown)
        .where(BacktestEquityPoint.run_id == run_id)
        .order_by(BacktestEquityPoint.ts)
    )
    rows = (await session.execute(stmt)).all()
    return tuple(
        EquityPoint(ts=row.ts, equity=Decimal(row.equity), drawdown=Decimal(row.drawdown))
        for row in rows
    )


async def has_recent_confirmed_candle(
    session: AsyncSession,
    instrument_id: int,
    *,
    bar: str,
    since: datetime,
) -> bool:
    stmt = (
        select(func.count())
        .select_from(Candle)
        .where(
            Candle.instrument_id == instrument_id,
            Candle.bar == bar,
            Candle.confirm.is_(True),
            Candle.open_time >= since,
        )
    )
    return bool((await session.execute(stmt)).scalar_one())


async def instrument_ids_by_inst_id(
    session: AsyncSession, inst_ids: tuple[str, ...]
) -> dict[str, int]:
    if not inst_ids:
        return {}
    stmt = select(Instrument.inst_id, Instrument.id).where(Instrument.inst_id.in_(inst_ids))
    rows = (await session.execute(stmt)).all()
    return {row.inst_id: row.id for row in rows}


__all__ = [
    "BacktestBaseline",
    "EquityPoint",
    "StrategyLegSpec",
    "StrategySource",
    "has_recent_confirmed_candle",
    "instrument_ids_by_inst_id",
    "latest_backtest_run",
    "list_approved_strategies",
    "load_equity_series",
    "load_legs",
    "load_strategy",
]

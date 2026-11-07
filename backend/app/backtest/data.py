"""回测输入读取：已入库策略行 + 已确认 K 线（只读）。

分层红线要求 `backtest` 不能 import `app.strategy`，因此这里用独立的
`MetaData` 声明两张只读表，跨 schema 直接查询；行情只读 `market` 的模型，
并且**强制 `confirm=true`**——未完成 bar 一律排除，绝不插值补齐。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Column,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.engine import Bar, BarSeries, LegSpec
from app.market.models import Candle, Instrument

# 只读表声明：只放回测真正用到的列，避免与 app.strategy.models 重复注册。
SOURCE_METADATA = MetaData()

STRATEGY_SOURCE = Table(
    "strategy",
    SOURCE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("name", Text),
    Column("kind", Text),
    Column("status", Text),
    Column("version", Integer),
    Column("content_hash", Text),
    schema="strategy",
)

STRATEGY_LEG_SOURCE = Table(
    "strategy_leg",
    SOURCE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("strategy_id", BigInteger),
    Column("instrument_id", BigInteger),
    Column("side", Text),
    Column("target_weight", Numeric(12, 10)),
    Column("rank", Integer),
    schema="strategy",
)


@dataclass(frozen=True, slots=True)
class StrategySource:
    """回测需要的策略头字段；状态在提交时校验，版本进入 `run_key`。"""

    id: int
    name: str
    kind: str
    status: str
    version: int
    content_hash: str


async def load_strategy_source(session: AsyncSession, strategy_id: int) -> StrategySource | None:
    row = (
        await session.execute(
            select(
                STRATEGY_SOURCE.c.id,
                STRATEGY_SOURCE.c.name,
                STRATEGY_SOURCE.c.kind,
                STRATEGY_SOURCE.c.status,
                STRATEGY_SOURCE.c.version,
                STRATEGY_SOURCE.c.content_hash,
            ).where(STRATEGY_SOURCE.c.id == strategy_id)
        )
    ).first()
    if row is None:
        return None
    return StrategySource(
        id=int(row.id),
        name=str(row.name),
        kind=str(row.kind),
        status=str(row.status),
        version=int(row.version),
        content_hash=str(row.content_hash),
    )


async def load_legs(session: AsyncSession, strategy_id: int) -> list[LegSpec]:
    rows = (
        await session.execute(
            select(
                STRATEGY_LEG_SOURCE.c.instrument_id,
                STRATEGY_LEG_SOURCE.c.side,
                STRATEGY_LEG_SOURCE.c.target_weight,
                STRATEGY_LEG_SOURCE.c.rank,
                Instrument.inst_id,
            )
            .join(Instrument, Instrument.id == STRATEGY_LEG_SOURCE.c.instrument_id)
            .where(STRATEGY_LEG_SOURCE.c.strategy_id == strategy_id)
            .order_by(STRATEGY_LEG_SOURCE.c.rank, STRATEGY_LEG_SOURCE.c.id)
        )
    ).all()
    return [
        LegSpec(
            instrument_id=int(row.instrument_id),
            inst_id=str(row.inst_id),
            side=str(row.side),
            target_weight=Decimal(row.target_weight),
            rank=int(row.rank),
        )
        for row in rows
    ]


@dataclass(frozen=True, slots=True)
class LoadedBars:
    series: dict[int, BarSeries]
    excluded_incomplete: dict[int, int]


async def load_bars(
    session: AsyncSession,
    *,
    instrument_ids: Sequence[int],
    bar: str,
    start: datetime,
    end: datetime,
) -> LoadedBars:
    """读取窗口内全部 bar；确认的进序列，未确认的只计数（`excluded_incomplete`）。"""

    rows = (
        await session.execute(
            select(Candle.instrument_id, Candle.open_time, Candle.close, Candle.confirm)
            .where(
                Candle.instrument_id.in_(list(instrument_ids)),
                Candle.bar == bar,
                Candle.open_time >= start,
                Candle.open_time < end,
            )
            .order_by(Candle.instrument_id, Candle.open_time)
        )
    ).all()

    confirmed: dict[int, list[Bar]] = {int(item): [] for item in instrument_ids}
    excluded: dict[int, int] = {int(item): 0 for item in instrument_ids}
    for row in rows:
        instrument_id = int(row.instrument_id)
        if row.confirm:
            confirmed[instrument_id].append(Bar(ts=row.open_time, close=Decimal(row.close)))
        else:
            excluded[instrument_id] += 1
    return LoadedBars(
        series={
            instrument_id: BarSeries(instrument_id=instrument_id, bars=tuple(bars))
            for instrument_id, bars in confirmed.items()
            if bars
        },
        excluded_incomplete={key: value for key, value in excluded.items() if value},
    )


async def count_confirmed(
    session: AsyncSession,
    *,
    instrument_id: int,
    bar: str,
    start: datetime,
    end: datetime,
) -> int:
    """窗口内已确认 bar 的数量；0 表示该标的数据不足，回测必须失败。"""

    total = await session.scalar(
        select(func.count())
        .select_from(Candle)
        .where(
            Candle.instrument_id == instrument_id,
            Candle.bar == bar,
            Candle.open_time >= start,
            Candle.open_time < end,
            Candle.confirm.is_(True),
        )
    )
    return int(total or 0)


__all__ = [
    "LoadedBars",
    "StrategySource",
    "count_confirmed",
    "load_bars",
    "load_legs",
    "load_strategy_source",
]

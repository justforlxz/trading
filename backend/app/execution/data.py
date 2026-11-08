"""execution 的只读数据访问：标的、策略审批状态、标记价格。

只查不写；写入一律走 `service.py` 与各编排模块，避免读路径夹带副作用。
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.market.models import Candle, Instrument
from app.strategy.models import Strategy


@dataclass(frozen=True, slots=True)
class InstrumentSource:
    id: int
    inst_id: str
    ct_val: Decimal
    lot_sz: Decimal


@dataclass(frozen=True, slots=True)
class StrategySource:
    id: int
    status: str
    kind: str


async def load_instrument(session: AsyncSession, inst_id: str) -> InstrumentSource | None:
    row = (
        await session.execute(select(Instrument).where(Instrument.inst_id == inst_id))
    ).scalar_one_or_none()
    if row is None:
        return None
    return InstrumentSource(id=row.id, inst_id=row.inst_id, ct_val=row.ct_val, lot_sz=row.lot_sz)


async def instrument_sizes(
    session: AsyncSession, inst_ids: tuple[str, ...] | list[str]
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """批量取 `ct_val` / `lot_sz`，供 OKX 适配器把基础币数量折算成张数。"""

    if not inst_ids:
        return {}, {}
    rows = (
        await session.execute(select(Instrument).where(Instrument.inst_id.in_(inst_ids)))
    ).scalars()
    contract_sizes: dict[str, Decimal] = {}
    lot_sizes: dict[str, Decimal] = {}
    for row in rows:
        contract_sizes[row.inst_id] = row.ct_val
        lot_sizes[row.inst_id] = row.lot_sz
    return contract_sizes, lot_sizes


async def load_strategy(session: AsyncSession, strategy_id: int) -> StrategySource | None:
    row = await session.get(Strategy, strategy_id)
    if row is None:
        return None
    return StrategySource(id=row.id, status=row.status, kind=row.kind)


async def latest_close(
    session: AsyncSession,
    instrument_id: int,
    *,
    bar: str,
    now: datetime | None = None,
) -> Decimal | None:
    """最近一根已确认 K 线的收盘价；只接受 `now` 之前的 K 线。"""

    moment = now or datetime.now(tz=UTC)
    row = (
        await session.execute(
            select(Candle.close)
            .where(
                Candle.instrument_id == instrument_id,
                Candle.bar == bar,
                Candle.confirm.is_(True),
                Candle.open_time <= moment,
            )
            .order_by(Candle.open_time.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


async def latest_closes(
    session: AsyncSession,
    instrument_ids: tuple[int, ...] | list[int],
    *,
    bar: str,
    lookback_days: int = 7,
    now: datetime | None = None,
) -> dict[int, Decimal]:
    """批量取每个标的最近一根确认 K 线收盘价（每个标的单独取最近一条）。"""

    if not instrument_ids:
        return {}
    moment = now or datetime.now(tz=UTC)
    since = moment - timedelta(days=lookback_days)
    rows = (
        await session.execute(
            select(Candle.instrument_id, Candle.close, Candle.open_time)
            .where(
                Candle.instrument_id.in_(instrument_ids),
                Candle.bar == bar,
                Candle.confirm.is_(True),
                Candle.open_time <= moment,
                Candle.open_time >= since,
            )
            .order_by(Candle.instrument_id, Candle.open_time.desc())
        )
    ).all()
    closes: dict[int, Decimal] = {}
    for instrument_id, close, _open_time in rows:
        closes.setdefault(instrument_id, close)
    return closes


__all__ = [
    "InstrumentSource",
    "StrategySource",
    "instrument_sizes",
    "latest_close",
    "latest_closes",
    "load_instrument",
    "load_strategy",
]

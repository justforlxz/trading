"""标的同步：OKX SWAP 全量入库（幂等 upsert）与查询。

落库约定（`docs/architecture/data-model.md` §3.1）：
- 唯一键 `inst_id`，重复同步只刷新 `source_synced_at` 与字段值，不产生新行；
- 分类由 `market/core/classification` 的维护表给出，未命中标 `unclassified`。
"""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.market.models import Instrument
from app.ports.market_data import InstrumentRow, InstrumentSource

UPSERT_FIELDS: tuple[str, ...] = (
    "inst_family",
    "uly",
    "inst_category",
    "asset_class",
    "exchange",
    "ct_val",
    "ct_val_ccy",
    "lot_sz",
    "min_sz",
    "tick_sz",
    "lever",
    "state",
    "rule_type",
    "list_time",
    "raw",
)


@dataclass(frozen=True, slots=True)
class SyncResult:
    """一次标的同步的结果摘要（写进 job_run.result）。"""

    fetched: int
    inserted: int
    updated: int
    by_asset_class: dict[str, int]


def _to_values(row: InstrumentRow, synced_at: datetime) -> dict[str, Any]:
    return {
        "inst_id": row.inst_id,
        "inst_family": row.inst_family,
        "uly": row.uly,
        "inst_category": row.inst_category,
        "asset_class": row.asset_class,
        "exchange": row.exchange,
        "ct_val": row.ct_val,
        "ct_val_ccy": row.ct_val_ccy,
        "lot_sz": row.lot_sz,
        "min_sz": row.min_sz,
        "tick_sz": row.tick_sz,
        "lever": row.lever,
        "state": row.state,
        "rule_type": row.rule_type,
        "list_time": row.list_time,
        "raw": row.raw,
        "source_synced_at": synced_at,
    }


async def sync_instruments(session: AsyncSession, source: InstrumentSource) -> SyncResult:
    """拉取全量标的并 upsert；返回新增/更新计数与分类分布。"""

    rows = await source.fetch_instruments()
    if not rows:
        raise ValueError("instrument source returned no rows")

    existing = set(await session.scalars(select(Instrument.inst_id)))
    synced_at = datetime.now(tz=UTC)
    values = [_to_values(row, synced_at) for row in rows]

    statement = pg_insert(Instrument).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=[Instrument.inst_id],
        set_={
            **{field: getattr(statement.excluded, field) for field in UPSERT_FIELDS},
            "source_synced_at": statement.excluded.source_synced_at,
        },
    )
    await session.execute(statement)
    await session.commit()

    inserted = sum(1 for row in rows if row.inst_id not in existing)
    distribution = Counter(row.asset_class for row in rows)
    return SyncResult(
        fetched=len(rows),
        inserted=inserted,
        updated=len(rows) - inserted,
        by_asset_class=dict(sorted(distribution.items())),
    )


async def count_instruments(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(Instrument)) or 0)


async def get_instrument(session: AsyncSession, inst_id: str) -> Instrument | None:
    return await session.scalar(select(Instrument).where(Instrument.inst_id == inst_id))


async def list_instruments(
    session: AsyncSession,
    *,
    limit: int = 50,
    cursor: str | None = None,
    asset_class: str | None = None,
    inst_category: int | None = None,
    query: str | None = None,
) -> tuple[list[Instrument], str | None]:
    """按 inst_id 升序的游标分页。"""

    statement = select(Instrument).order_by(Instrument.inst_id).limit(limit + 1)
    if cursor:
        statement = statement.where(Instrument.inst_id > cursor)
    if asset_class:
        statement = statement.where(Instrument.asset_class == asset_class)
    if inst_category is not None:
        statement = statement.where(Instrument.inst_category == inst_category)
    if query:
        statement = statement.where(Instrument.inst_id.ilike(f"%{query}%"))
    rows = list(await session.scalars(statement))
    next_cursor = rows[limit - 1].inst_id if len(rows) > limit else None
    return rows[:limit], next_cursor


__all__ = [
    "SyncResult",
    "count_instruments",
    "get_instrument",
    "list_instruments",
    "sync_instruments",
]

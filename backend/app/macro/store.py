"""宏观观测的落库与读回。

写：`macro_observations` 按 `(series_id, ts, provider)` 唯一键 upsert，重复抓取只更新，
不产生副本。

读：一次查询取回每个「序列 + 来源」最近两个交易日的末条观测——最新一条用来显示，前
一个交易日那条用来算日变化。一条 SQL 覆盖整个总览，不按行逐条查（总览一次要 5 行）。
两个查询都带 `provider` 条件：换源后旧源的历史仍在表里，不能被读成当前值。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from app.core import Observation, SystemClock
from app.db import session_scope
from app.macro.model import MacroObservationRow

__all__ = [
    "ObservationRecord",
    "StoredObservation",
    "has_trading_day",
    "latest_ts",
    "recent_map",
    "save_observations",
]

#: 一次 upsert 的行数上限；分钟级一次 tick 可能上千行，分批避免单条语句过长。
BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    """一条待落库的观测：原始值 + 由 enrich 中间件算出的派生字段。"""

    observation: Observation
    trading_day: date
    market_session: str


@dataclass(frozen=True, slots=True)
class StoredObservation:
    """读回的一条观测值。"""

    series_id: str
    ts: int
    value: Decimal
    provider: str
    trading_day: date
    market_session: str
    is_delayed: bool
    fetched_at: datetime


def _point(row: MacroObservationRow) -> StoredObservation:
    return StoredObservation(
        series_id=row.series_id,
        ts=row.ts,
        value=row.value,
        provider=row.provider,
        trading_day=row.trading_day,
        market_session=row.market_session,
        is_delayed=row.is_delayed,
        fetched_at=row.fetched_at,
    )


def save_observations(
    records: Sequence[ObservationRecord],
    *,
    now: datetime | None = None,
) -> int:
    """按唯一键 upsert 一批观测，返回提交的行数（含被覆盖的重复行）。"""

    if not records:
        return 0
    moment = now or SystemClock().now()
    rows = [
        {
            "series_id": record.observation.series_id,
            "ts": record.observation.ts,
            "provider": record.observation.provider,
            "value": record.observation.value,
            "trading_day": record.trading_day,
            "market_session": record.market_session,
            "is_delayed": record.observation.is_delayed,
            "fetched_at": moment,
        }
        for record in records
    ]
    with session_scope() as session:
        for offset in range(0, len(rows), BATCH_SIZE):
            statement = postgresql_insert(MacroObservationRow).values(
                rows[offset : offset + BATCH_SIZE]
            )
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=["series_id", "ts", "provider"],
                    set_={
                        "value": statement.excluded.value,
                        "trading_day": statement.excluded.trading_day,
                        "market_session": statement.excluded.market_session,
                        "is_delayed": statement.excluded.is_delayed,
                        "fetched_at": statement.excluded.fetched_at,
                    },
                )
            )
    return len(rows)


def recent_map(
    pairs: Iterable[tuple[str, str]],
) -> dict[tuple[str, str], tuple[StoredObservation, ...]]:
    """每个「序列 + 来源」最近两个交易日的末条观测，按交易日倒序，最多两条。

    先按「序列 + 来源 + 交易日」取当日最后一条，再在每个组合内按交易日排名取前二：
    第一条是当前值，第二条是上一个交易日的收盘值（日变化用它）。没有观测的组合不出现。
    """

    wanted = list(dict.fromkeys(pairs))
    if not wanted:
        return {}
    per_day = (
        select(
            MacroObservationRow.series_id,
            MacroObservationRow.provider,
            MacroObservationRow.trading_day,
            MacroObservationRow.ts,
            MacroObservationRow.value,
            MacroObservationRow.market_session,
            MacroObservationRow.is_delayed,
            MacroObservationRow.fetched_at,
        )
        .where(MacroObservationRow.series_id.in_({item[0] for item in wanted}))
        .where(MacroObservationRow.provider.in_({item[1] for item in wanted}))
        .distinct(
            MacroObservationRow.series_id,
            MacroObservationRow.provider,
            MacroObservationRow.trading_day,
        )
        .order_by(
            MacroObservationRow.series_id,
            MacroObservationRow.provider,
            MacroObservationRow.trading_day,
            MacroObservationRow.ts.desc(),
        )
        .subquery()
    )
    ranked = select(
        per_day,
        func.row_number()
        .over(
            partition_by=(per_day.c.series_id, per_day.c.provider),
            order_by=per_day.c.trading_day.desc(),
        )
        .label("rank"),
    ).subquery()
    statement = (
        select(ranked)
        .where(ranked.c.rank <= 2)
        .order_by(ranked.c.series_id, ranked.c.provider, ranked.c.trading_day.desc())
    )
    with session_scope() as session:
        rows = list(session.execute(statement))
    allowed = set(wanted)
    grouped: dict[tuple[str, str], list[StoredObservation]] = {}
    for row in rows:
        key = (row.series_id, row.provider)
        if key not in allowed:
            continue
        grouped.setdefault(key, []).append(_point(row))
    return {key: tuple(points) for key, points in grouped.items()}


def has_trading_day(series_id: str, provider: str, day: date) -> bool:
    """该「序列 + 来源」是否已经有这个交易日的观测；日线源用它判重，避免重抓。"""

    statement = (
        select(MacroObservationRow.ts)
        .where(
            MacroObservationRow.series_id == series_id,
            MacroObservationRow.provider == provider,
            MacroObservationRow.trading_day == day,
        )
        .limit(1)
    )
    with session_scope() as session:
        return session.execute(statement).first() is not None


def latest_ts(series_id: str, provider: str) -> int | None:
    """该「序列 + 来源」已有观测的最大 `ts`；增量抓取用它当 `since`。"""

    statement = (
        select(MacroObservationRow.ts)
        .where(
            MacroObservationRow.series_id == series_id,
            MacroObservationRow.provider == provider,
        )
        .order_by(MacroObservationRow.ts.desc())
        .limit(1)
    )
    with session_scope() as session:
        return session.execute(statement).scalar_one_or_none()

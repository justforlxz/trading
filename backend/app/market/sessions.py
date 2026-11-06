"""交易日历落库与查询：把 `core.calendar` 的规则结果持久化为 `market.market_session`。"""

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.market.core.calendar import CALENDAR_SOURCE, VENUE, iter_sessions
from app.market.models import MarketSession

CALENDAR_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class SessionSyncResult:
    from_date: date
    to_date: date
    written: int
    trading_days: int


async def sync_sessions(session: AsyncSession, *, start: date, end: date) -> SessionSyncResult:
    """按日期区间 upsert 日历（含非交易日，`is_session=False`）。"""

    windows = list(iter_sessions(start, end))
    payload = [
        {
            "venue": VENUE,
            "trading_date": window.trading_date,
            "is_session": window.is_session,
            "is_half_day": window.is_half_day,
            "is_holiday": window.is_holiday,
            "pre_start": window.pre_start,
            "pre_end": window.pre_end,
            "regular_start": window.regular_start,
            "regular_end": window.regular_end,
            "post_start": window.post_start,
            "post_end": window.post_end,
            "calendar_source": CALENDAR_SOURCE,
            "calendar_version": CALENDAR_VERSION,
        }
        for window in windows
    ]
    if payload:
        statement = pg_insert(MarketSession).values(payload)
        statement = statement.on_conflict_do_update(
            constraint="uq_market_session_key",
            set_={
                "is_session": statement.excluded.is_session,
                "is_half_day": statement.excluded.is_half_day,
                "is_holiday": statement.excluded.is_holiday,
                "pre_start": statement.excluded.pre_start,
                "pre_end": statement.excluded.pre_end,
                "regular_start": statement.excluded.regular_start,
                "regular_end": statement.excluded.regular_end,
                "post_start": statement.excluded.post_start,
                "post_end": statement.excluded.post_end,
                "calendar_source": statement.excluded.calendar_source,
                "calendar_version": statement.excluded.calendar_version,
            },
        )
        await session.execute(statement)
        await session.commit()
    return SessionSyncResult(
        from_date=start,
        to_date=end,
        written=len(payload),
        trading_days=sum(1 for window in windows if window.is_session),
    )


async def list_sessions(session: AsyncSession, *, start: date, end: date) -> list[MarketSession]:
    statement = (
        select(MarketSession)
        .where(
            MarketSession.trading_date >= start,
            MarketSession.trading_date <= end,
            MarketSession.venue == "XNYS",
        )
        .order_by(MarketSession.trading_date)
    )
    return list(await session.scalars(statement))


def session_payload(row: MarketSession) -> dict[str, object]:
    return {
        "venue": row.venue,
        "trading_date": row.trading_date.isoformat(),
        "is_session": row.is_session,
        "is_half_day": row.is_half_day,
        "is_holiday": row.is_holiday,
        "pre_start": _iso(row.pre_start),
        "pre_end": _iso(row.pre_end),
        "regular_start": _iso(row.regular_start),
        "regular_end": _iso(row.regular_end),
        "post_start": _iso(row.post_start),
        "post_end": _iso(row.post_end),
        "calendar_source": row.calendar_source,
        "calendar_version": row.calendar_version,
    }


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


__all__ = [
    "CALENDAR_SOURCE",
    "SessionSyncResult",
    "list_sessions",
    "session_payload",
    "sync_sessions",
]

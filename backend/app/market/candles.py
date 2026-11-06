"""合约 K 线：幂等写入、增量采集、历史回补、缺口登记与查询。

关键约定：
- 唯一键 `(instrument_id, bar, open_time)`，重复回补只更新值，不产生副本；
- 已确认（confirm=true）的 bar 不会被后来的未完成 bar 覆盖（回补前先过滤）；
- 采集失败（限流耗尽等）由任务层收敛为 `partial`，缺口写 `data_quality_issue`。
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.market.core.bars import bar_seconds, normalize_bar
from app.market.core.candles import find_gaps
from app.market.core.coverage import coverage_by_day, summarize
from app.market.models import Candle, Instrument
from app.ops.quality import record_issue
from app.ports.market_data import CandleRow, CandleSource

DATASET = "market.candle"

VALUE_FIELDS: tuple[str, ...] = (
    "open",
    "high",
    "low",
    "close",
    "vol",
    "vol_ccy",
    "vol_ccy_quote",
    "source",
)


@dataclass(frozen=True, slots=True)
class BackfillResult:
    """回补结果：写入行数 + 未补齐的窗口（空表示完整）。"""

    inst_id: str
    bar: str
    rows_written: int
    gaps: list[tuple[datetime, datetime]] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "partial" if self.gaps else "ok"


def _values(
    instrument_id: int, rows: list[CandleRow], ingested_at: datetime
) -> list[dict[str, Any]]:
    return [
        {
            "instrument_id": instrument_id,
            "bar": row.bar,
            "open_time": row.open_time,
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "vol": row.vol,
            "vol_ccy": row.vol_ccy,
            "vol_ccy_quote": row.vol_ccy_quote,
            "confirm": row.confirm,
            "source": row.source,
            "ingested_at": ingested_at,
        }
        for row in rows
    ]


async def _confirmed_open_times(
    session: AsyncSession, instrument_id: int, bar: str, rows: list[CandleRow]
) -> set[datetime]:
    if not rows:
        return set()
    times = [row.open_time for row in rows]
    statement = select(Candle.open_time).where(
        Candle.instrument_id == instrument_id,
        Candle.bar == bar,
        Candle.open_time.in_(times),
        Candle.confirm.is_(True),
    )
    return set(await session.scalars(statement))


async def upsert_candles(session: AsyncSession, instrument_id: int, rows: list[CandleRow]) -> int:
    """幂等写入；已确认的 bar 不被未完成版本覆盖。返回提交的行数。"""

    if not rows:
        return 0
    confirmed = await _confirmed_open_times(session, instrument_id, rows[0].bar, rows)
    usable = [row for row in rows if row.confirm or row.open_time not in confirmed]
    if not usable:
        return 0

    payload = _values(instrument_id, usable, datetime.now(tz=UTC))
    statement = pg_insert(Candle).values(payload)
    statement = statement.on_conflict_do_update(
        index_elements=[Candle.instrument_id, Candle.bar, Candle.open_time],
        set_={
            **{name: getattr(statement.excluded, name) for name in VALUE_FIELDS},
            "confirm": Candle.confirm.is_(True) | statement.excluded.confirm,
            "ingested_at": statement.excluded.ingested_at,
        },
    )
    await session.execute(statement)
    await session.commit()
    return len(usable)


async def latest_open_time(session: AsyncSession, instrument_id: int, bar: str) -> datetime | None:
    return await session.scalar(
        select(func.max(Candle.open_time)).where(
            Candle.instrument_id == instrument_id, Candle.bar == bar
        )
    )


def _gap_window(bar: str, now: datetime) -> tuple[datetime, datetime]:
    """缺口检测窗口：日线看 30 天，日内看 3 天（足够覆盖停摆排查）。"""

    days = 30 if bar == "1d" else 3
    return now - timedelta(days=days), now


async def record_gaps(
    session: AsyncSession,
    *,
    instrument: Instrument,
    bar: str,
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, datetime]]:
    """对比「应到」与「实到」，把缺口登记为 GAP 问题（幂等）。"""

    actual = set(
        await session.scalars(
            select(Candle.open_time).where(
                Candle.instrument_id == instrument.id,
                Candle.bar == bar,
                Candle.open_time >= start,
                Candle.open_time < end,
            )
        )
    )
    gaps = find_gaps(actual, start, end, bar)
    for gap_start, gap_end in gaps:
        await record_issue(
            session,
            dataset=DATASET,
            scope_id=f"{instrument.inst_id}:{bar}",
            kind="GAP",
            window_start=gap_start,
            window_end=gap_end,
            severity="warning",
            detail={
                "inst_id": instrument.inst_id,
                "bar": bar,
                "expected_seconds": bar_seconds(bar),
            },
        )
    return gaps


async def record_collection_gap(
    session: AsyncSession,
    *,
    instrument: Instrument,
    bar: str,
    now: datetime | None = None,
    reason: str = "upstream_unavailable",
) -> datetime:
    """采集彻底失败时登记「待补窗口」，起点从最后一根之后算起。

    起点与 `record_gaps` 的缺口起点同口径，等数据补齐后同一条记录会自然收敛。
    """

    moment = now or datetime.now(tz=UTC)
    normalized = normalize_bar(bar)
    window_start, _ = _gap_window(normalized, moment)
    latest = await latest_open_time(session, instrument.id, normalized)
    step = timedelta(seconds=bar_seconds(normalized))
    expected = latest + step if latest is not None else window_start
    start = max(expected, window_start)
    await record_issue(
        session,
        dataset=DATASET,
        scope_id=f"{instrument.inst_id}:{normalized}",
        kind="GAP",
        window_start=start,
        window_end=moment,
        severity="warning",
        detail={
            "inst_id": instrument.inst_id,
            "bar": normalized,
            "reason": reason,
            "expected_seconds": bar_seconds(normalized),
        },
    )
    await session.commit()
    return start


async def ingest_recent(
    session: AsyncSession,
    source: CandleSource,
    *,
    instrument: Instrument,
    bars: list[str],
    limit: int = 300,
    now: datetime | None = None,
) -> dict[str, int]:
    """增量采集：每根周期取最近 N 根并 upsert，随后登记缺口。"""

    moment = now or datetime.now(tz=UTC)
    written: dict[str, int] = {}
    for bar in bars:
        normalized = normalize_bar(bar)
        rows = await source.fetch_candles(instrument.inst_id, normalized, limit=limit)
        written[normalized] = await upsert_candles(session, instrument.id, rows)
        start, end = _gap_window(normalized, moment)
        await record_gaps(session, instrument=instrument, bar=normalized, start=start, end=end)
    await session.commit()
    return written


async def backfill(
    session: AsyncSession,
    source: CandleSource,
    *,
    instrument: Instrument,
    bar: str,
    start: datetime,
    end: datetime,
    page_limit: int = 100,
) -> BackfillResult:
    """历史回补指定窗口，随后按 `[start, end)` 登记缺口。"""

    normalized = normalize_bar(bar)
    rows = await source.fetch_history(
        instrument.inst_id, normalized, start, end, page_limit=page_limit
    )
    written = await upsert_candles(session, instrument.id, rows)
    gaps = await record_gaps(session, instrument=instrument, bar=normalized, start=start, end=end)
    await session.commit()
    return BackfillResult(
        inst_id=instrument.inst_id, bar=normalized, rows_written=written, gaps=gaps
    )


async def coverage(
    session: AsyncSession,
    *,
    instrument: Instrument,
    bar: str,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """应到/实到/缺口的窗口汇总（逐日明细由 `core.coverage` 计算）。"""

    normalized = normalize_bar(bar)
    actual = list(
        await session.scalars(
            select(Candle.open_time).where(
                Candle.instrument_id == instrument.id,
                Candle.bar == normalized,
                Candle.open_time >= start,
                Candle.open_time < end,
            )
        )
    )
    buckets = coverage_by_day(actual, start, end, normalized)
    return {
        "inst_id": instrument.inst_id,
        "bar": normalized,
        "window_start": start,
        "window_end": end,
        "summary": summarize(buckets),
        "days": [bucket.as_dict() for bucket in buckets],
    }


async def list_candles(
    session: AsyncSession,
    *,
    inst_id: str,
    bar: str,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 200,
    cursor: datetime | None = None,
) -> tuple[list[Candle], datetime | None]:
    """固定按 open_time 升序的分页（契约例外：行情序列必须升序）。"""

    normalized = normalize_bar(bar)
    statement = (
        select(Candle)
        .join(Instrument, Instrument.id == Candle.instrument_id)
        .where(Instrument.inst_id == inst_id, Candle.bar == normalized)
        .order_by(Candle.open_time)
        .limit(limit + 1)
    )
    if start is not None:
        statement = statement.where(Candle.open_time >= start)
    if end is not None:
        statement = statement.where(Candle.open_time < end)
    if cursor is not None:
        statement = statement.where(Candle.open_time > cursor)
    rows = list(await session.scalars(statement))
    next_cursor = rows[limit - 1].open_time if len(rows) > limit else None
    return rows[:limit], next_cursor


def expected_window_end(start: datetime, end: datetime, bar: str) -> datetime:
    """把 `[start, end)` 对齐到周期边界，供覆盖率与缺口计算共用。"""

    return end if end > start else start + timedelta(seconds=bar_seconds(bar))


__all__ = [
    "DATASET",
    "BackfillResult",
    "backfill",
    "coverage",
    "expected_window_end",
    "ingest_recent",
    "latest_open_time",
    "list_candles",
    "record_collection_gap",
    "record_gaps",
    "upsert_candles",
]

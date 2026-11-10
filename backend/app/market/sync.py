"""历史 K 线下载与落库：向前分页、只取已收盘、幂等 upsert。

这一层只做 IO 与事务边界：分页取数、窗口过滤、一次事务写入；
缺口、重复、对齐这些判断复用 `app.market.candles` 的纯函数。
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from app.core import Bar, MarketDataPort, Timeframe, ValidationError
from app.db import session_scope
from app.market.candles import dedupe_sorted, floor_open_time
from app.market.model import Candle, from_epoch, to_epoch
from app.shared import bar_seconds, normalize_bar

# 上游单次请求的 K 线上限；`page_limit` 不得超过它，否则适配层直接报错。
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_LIMIT = MAX_PAGE_LIMIT

# 单条 INSERT 的批量上限：PostgreSQL 单条语句最多 65535 个绑定参数，每行 10 个值
# 约合 6553 行；取 1000 留足余量，保证极大窗口也不会撞上参数上限。
UPSERT_BATCH_SIZE = 1000


@dataclass(frozen=True, slots=True)
class SyncResult:
    """一次同步的结果：下载了多少、新写入多少、覆盖多少、丢了多少未收盘。"""

    symbol: str
    bar: str
    downloaded: int
    inserted: int
    updated: int
    skipped_unconfirmed: int
    pages: int


@dataclass(frozen=True, slots=True)
class UpsertResult:
    """一次幂等写入的结果。"""

    inserted: int
    updated: int
    skipped_unconfirmed: int


def normalize_bar_or_raise(bar: str) -> str:
    """把周期归一化成规范写法；未知周期按调用方错误处理。"""

    try:
        return normalize_bar(bar)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def require_range(start: datetime, end: datetime) -> None:
    """区间必须是带时区的半开窗口 `[start, end)`，且 `start < end`。"""

    if start.tzinfo is None or end.tzinfo is None:
        raise ValidationError("start/end 必须是带时区的时间")
    if start >= end:
        raise ValidationError(f"start 必须早于 end:{start.isoformat()} >= {end.isoformat()}")


def first_open_time(start: datetime, bar: str) -> datetime:
    """`[start, end)` 窗口里第一个可能的 open_time（对齐到周期边界）。"""

    aligned = floor_open_time(start, bar)
    step = timedelta(seconds=bar_seconds(bar))
    return aligned if aligned >= start else aligned + step


def sync_candles(
    port: MarketDataPort,
    symbol: str,
    bar: str,
    start: datetime,
    end: datetime,
    *,
    page_limit: int = DEFAULT_PAGE_LIMIT,
) -> SyncResult:
    """下载 `[start, end)` 的历史 K 线并幂等落库。

    从 `end` 往前翻页，直到覆盖 `start`、上游返回空页、或游标不再前进。
    只把窗口内已收盘的 K 线写进历史表；缺口不补造——缺多少由 `integrity` 报。
    """

    canonical = normalize_bar_or_raise(bar)
    require_range(start, end)
    if not 1 <= page_limit <= MAX_PAGE_LIMIT:
        raise ValidationError(f"page_limit 必须在 1..{MAX_PAGE_LIMIT} 之间")
    timeframe = Timeframe.parse(canonical)
    window_start = first_open_time(start, canonical)

    collected: list[Bar] = []
    cursor = end
    pages = 0
    while True:
        page = port.history_candles(symbol, timeframe, after=cursor, limit=page_limit)
        if not page:
            break
        pages += 1
        collected.extend(candle for candle in page if window_start <= candle.open_time < end)
        earliest = min(candle.open_time for candle in page)
        if earliest <= window_start or earliest >= cursor:
            break
        cursor = earliest

    rows = dedupe_sorted(collected, key=lambda candle: candle.open_time)
    written = upsert_candles(rows)
    return SyncResult(
        symbol=symbol,
        bar=canonical,
        downloaded=len(rows),
        inserted=written.inserted,
        updated=written.updated,
        skipped_unconfirmed=written.skipped_unconfirmed,
        pages=pages,
    )


def upsert_candles(rows: Iterable[Bar]) -> UpsertResult:
    """批量幂等写入：同一主键重复写不新增行，只覆盖价格。

    写入按固定行数切块，避免大窗口一次性撞上 PostgreSQL 的绑定参数上限；
    同一批内的重复主键先合并，计数只按唯一主键算。"""

    prepared: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    skipped = 0
    for candle in rows:
        if not candle.confirm:
            skipped += 1
            continue
        row = Candle.from_bar(candle)
        prepared[(row.symbol, row.bar, row.open_time, row.source)] = {
            "symbol": row.symbol,
            "bar": row.bar,
            "open_time": row.open_time,
            "source": row.source,
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "volume": row.volume,
            "updated_at": row.updated_at,
        }
    if not prepared:
        return UpsertResult(inserted=0, updated=0, skipped_unconfirmed=skipped)

    existing: set[tuple[str, str, int, str]] = set()
    with session_scope() as session:
        for batch in _batches(list(prepared.values()), UPSERT_BATCH_SIZE):
            existing |= _existing_keys(session, batch)
            statement = postgresql_insert(Candle).values(batch)
            statement = statement.on_conflict_do_update(
                index_elements=["symbol", "bar", "open_time", "source"],
                set_={
                    "open": statement.excluded.open,
                    "high": statement.excluded.high,
                    "low": statement.excluded.low,
                    "close": statement.excluded.close,
                    "volume": statement.excluded.volume,
                    "updated_at": statement.excluded.updated_at,
                },
            )
            session.execute(statement)

    return UpsertResult(
        inserted=len(prepared) - len(existing),
        updated=len(existing),
        skipped_unconfirmed=skipped,
    )


def _batches(items: Sequence[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    """把待写行切成固定大小的批次。"""

    for offset in range(0, len(items), size):
        yield list(items[offset : offset + size])


def load_candles(
    symbol: str,
    bar: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    source: str | None = None,
) -> list[Bar]:
    """按 open_time 升序读出历史 K 线；`start`/`end` 为半开窗口。"""

    canonical = normalize_bar_or_raise(bar)
    if start is not None and end is not None:
        require_range(start, end)
    statement = select(Candle).where(Candle.symbol == symbol, Candle.bar == canonical)
    if start is not None:
        statement = statement.where(Candle.open_time >= to_epoch(start))
    if end is not None:
        statement = statement.where(Candle.open_time < to_epoch(end))
    if source is not None:
        statement = statement.where(Candle.source == source)
    statement = statement.order_by(Candle.open_time)
    with session_scope() as session:
        return [row.to_bar() for row in session.scalars(statement)]


def data_range(
    symbol: str,
    bar: str,
    *,
    source: str | None = None,
) -> tuple[datetime, datetime] | None:
    """库里真实的首末 K 线 open_time；没有数据返回 `None`，不补齐、不外推。"""

    canonical = normalize_bar_or_raise(bar)
    statement = select(func.min(Candle.open_time), func.max(Candle.open_time)).where(
        Candle.symbol == symbol, Candle.bar == canonical
    )
    if source is not None:
        statement = statement.where(Candle.source == source)
    with session_scope() as session:
        first, last = session.execute(statement).one()
    if first is None:
        return None
    return from_epoch(int(first)), from_epoch(int(last))


def _existing_keys(
    session: Any, prepared: Sequence[dict[str, Any]]
) -> set[tuple[str, str, int, str]]:
    """查出这批行里已经存在的主键，用于区分 inserted / updated。"""

    grouped: dict[tuple[str, str, str], list[int]] = {}
    for row in prepared:
        grouped.setdefault((row["symbol"], row["bar"], row["source"]), []).append(row["open_time"])
    existing: set[tuple[str, str, int, str]] = set()
    for (symbol, bar, source), open_times in grouped.items():
        found = session.scalars(
            select(Candle.open_time).where(
                Candle.symbol == symbol,
                Candle.bar == bar,
                Candle.source == source,
                Candle.open_time.in_(open_times),
            )
        )
        existing.update((symbol, bar, open_time, source) for open_time in found)
    return existing

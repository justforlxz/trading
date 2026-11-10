"""K 线的纯函数：对齐、排序/去重、缺口定位、confirm 归并。

不碰数据库、不发 HTTP，便于单测给出确定的输入/输出。
"""

from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime, timedelta
from itertools import pairwise

from app.market.session import daily_open_time, next_daily_open_time
from app.shared import bar_seconds, normalize_bar


def bar_delta(bar: str) -> timedelta:
    return timedelta(seconds=bar_seconds(bar))


def floor_open_time(ts: datetime, bar: str, asset_type: str) -> datetime:
    """把时间戳向下对齐到该周期的 open_time（UTC）。

    日线的定界不是全局常量，也不是自然日零点：它由 `asset_type` 所属市场的交易时段
    决定（`app.market.session.daily_open_time`，24/7 市场仍是 OKX 的 UTC+8 零点）。
    其余周期按固定步长对齐，与资产无关。
    """

    if ts.tzinfo is None:
        raise ValueError("ts must be timezone-aware")
    canonical = normalize_bar(bar)
    utc = ts.astimezone(UTC)
    if canonical == "1d":
        return daily_open_time(asset_type, utc)
    epoch = int(utc.timestamp())
    step = bar_seconds(canonical)
    return datetime.fromtimestamp(epoch - epoch % step, tz=UTC)


def next_open_time(cursor: datetime, bar: str, asset_type: str) -> datetime:
    """`cursor` 之后的下一个 open_time。

    日线按交易时段推进（美股跳过周末与休市日，24/7 资产每天一根），其余周期按固定
    步长推进——日线不是均匀网格，不能用「加 24 小时」代替。
    """

    if normalize_bar(bar) == "1d":
        return next_daily_open_time(asset_type, cursor)
    return cursor + bar_delta(bar)


def expected_open_times(
    start: datetime, end: datetime, bar: str, asset_type: str
) -> list[datetime]:
    """`[start, end)` 内应到的 open_time 序列（含缺口检测的分母）。"""

    cursor = floor_open_time(start, bar, asset_type)
    if cursor < start:
        cursor = next_open_time(cursor, bar, asset_type)
    result: list[datetime] = []
    while cursor < end:
        result.append(cursor)
        cursor = next_open_time(cursor, bar, asset_type)
    return result


def dedupe_sorted[T](rows: Iterable[T], key: Callable[[T], object]) -> list[T]:
    """按 key 去重并升序；同一 open_time 保留最后一条（后到覆盖先到）。"""

    latest: dict[object, T] = {}
    for row in rows:
        latest[key(row)] = row
    return [latest[k] for k in sorted(latest)]


def find_gaps(
    actual: Sequence[datetime],
    start: datetime,
    end: datetime,
    bar: str,
    asset_type: str,
) -> list[tuple[datetime, datetime]]:
    """返回缺口窗口 `[window_start, window_end)`，按时间升序合并连续缺失。"""

    present = set(actual)
    gaps: list[tuple[datetime, datetime]] = []
    run_start: datetime | None = None
    cursor: datetime | None = None
    for expected in expected_open_times(start, end, bar, asset_type):
        cursor = expected
        if expected in present:
            if run_start is not None:
                gaps.append((run_start, expected))
                run_start = None
        elif run_start is None:
            run_start = expected
    if run_start is not None and cursor is not None:
        gaps.append((run_start, next_open_time(cursor, bar, asset_type)))
    return gaps


def duplicate_open_times(actual: Sequence[datetime]) -> list[datetime]:
    """重复出现的 open_time（数据质量 DUPLICATE 判定）。"""

    seen: set[datetime] = set()
    duplicates: list[datetime] = []
    for ts in actual:
        if ts in seen and ts not in duplicates:
            duplicates.append(ts)
        seen.add(ts)
    return duplicates


def out_of_order(actual: Sequence[datetime]) -> bool:
    """序列是否非严格升序。"""

    return any(later <= earlier for earlier, later in pairwise(actual))

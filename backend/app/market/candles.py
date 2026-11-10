"""K 线的纯函数：对齐、排序/去重、缺口定位、confirm 归并。

不碰数据库、不发 HTTP，便于单测给出确定的输入/输出。
"""

from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime, timedelta, timezone
from itertools import pairwise

from app.shared.timeframe import bar_seconds, normalize_bar

# OKX 的 1D 以 UTC+8 为零点，内部仍用 UTC 存储，因此日线边界落在 16:00Z。
UTC8 = timezone(timedelta(hours=8))


def bar_delta(bar: str) -> timedelta:
    return timedelta(seconds=bar_seconds(bar))


def floor_open_time(ts: datetime, bar: str) -> datetime:
    """把时间戳向下对齐到该周期的 open_time（UTC）。"""

    if ts.tzinfo is None:
        raise ValueError("ts must be timezone-aware")
    canonical = normalize_bar(bar)
    utc = ts.astimezone(UTC)
    if canonical == "1d":
        local = utc.astimezone(UTC8)
        floored = local.replace(hour=0, minute=0, second=0, microsecond=0)
        return floored.astimezone(UTC)
    epoch = int(utc.timestamp())
    step = bar_seconds(canonical)
    return datetime.fromtimestamp(epoch - epoch % step, tz=UTC)


def expected_open_times(start: datetime, end: datetime, bar: str) -> list[datetime]:
    """`[start, end)` 内应到的 open_time 序列（含缺口检测的分母）。"""

    step = bar_delta(bar)
    cursor = floor_open_time(start, bar)
    if cursor < start:
        cursor += step
    result: list[datetime] = []
    while cursor < end:
        result.append(cursor)
        cursor += step
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
) -> list[tuple[datetime, datetime]]:
    """返回缺口窗口 `[window_start, window_end)`，按时间升序合并连续缺失。"""

    present = set(actual)
    gaps: list[tuple[datetime, datetime]] = []
    step = bar_delta(bar)
    run_start: datetime | None = None
    cursor: datetime | None = None
    for expected in expected_open_times(start, end, bar):
        cursor = expected
        if expected in present:
            if run_start is not None:
                gaps.append((run_start, expected))
                run_start = None
        elif run_start is None:
            run_start = expected
    if run_start is not None and cursor is not None:
        gaps.append((run_start, cursor + step))
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

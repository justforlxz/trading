"""覆盖率计算（纯函数）：逐日应到 / 实到 / 缺口窗口。

「应到」由周期与时间窗口推导，「实到」来自库内 open_time 集合；
差异按自然日（UTC）切桶，输出落到具体 `window_start` 的缺口，供
`GET /market/coverage` 与 `data_quality_issue` 共用同一口径。
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.market.core.candles import bar_delta, expected_open_times, find_gaps


@dataclass(frozen=True, slots=True)
class CoverageBucket:
    """一个自然日的覆盖情况。"""

    window_start: datetime
    window_end: datetime
    expected: int
    actual: int
    gaps: list[tuple[datetime, datetime]] = field(default_factory=list)

    @property
    def missing(self) -> int:
        return max(self.expected - self.actual, 0)

    @property
    def ratio(self) -> float:
        return 1.0 if self.expected == 0 else self.actual / self.expected

    def as_dict(self) -> dict[str, object]:
        """API 用的可序列化形式（时间为 ISO-8601 UTC）。"""

        return {
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "expected": self.expected,
            "actual": self.actual,
            "missing": self.missing,
            "ratio": self.ratio,
            "gaps": [
                {"window_start": start.isoformat(), "window_end": end.isoformat()}
                for start, end in self.gaps
            ],
        }


def coverage_by_day(
    actual: Sequence[datetime],
    start: datetime,
    end: datetime,
    bar: str,
) -> list[CoverageBucket]:
    """按 UTC 自然日切桶，统计期望/实际数量并定位缺口。"""

    present = {ts.astimezone(UTC) for ts in actual}
    buckets: dict[object, list[datetime]] = {}
    for expected in expected_open_times(start, end, bar):
        buckets.setdefault(expected.astimezone(UTC).date(), []).append(expected)

    step = bar_delta(bar)
    result: list[CoverageBucket] = []
    for day in sorted(buckets):
        expected_times = buckets[day]
        window_start = expected_times[0]
        window_end = expected_times[-1] + step
        actual_times = [ts for ts in expected_times if ts in present]
        result.append(
            CoverageBucket(
                window_start=window_start,
                window_end=window_end,
                expected=len(expected_times),
                actual=len(actual_times),
                gaps=find_gaps(actual_times, window_start, window_end, bar),
            )
        )
    return result


def summarize(buckets: Sequence[CoverageBucket]) -> dict[str, object]:
    """整体覆盖率汇总，供 `/market/coverage` 顶层字段使用。"""

    expected = sum(b.expected for b in buckets)
    actual = sum(b.actual for b in buckets)
    return {
        "expected": expected,
        "actual": actual,
        "missing": max(expected - actual, 0),
        "ratio": 1.0 if expected == 0 else actual / expected,
    }

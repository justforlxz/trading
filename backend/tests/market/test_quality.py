"""数据质量（AC8）：跳变检测、问题登记幂等、覆盖率缺口定位。"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.market.core.coverage import coverage_by_day, summarize
from app.market.models import DataQualityIssue
from app.ops.quality import detect_price_jumps, record_issue
from tests.market.support import make_candle_rows

START = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)


def test_detect_price_jumps_flags_large_move() -> None:
    rows = make_candle_rows(start=START, count=3)
    rows[2] = replace(rows[2], close=Decimal("600"))
    outliers = detect_price_jumps(rows, threshold_ratio=0.2)
    assert len(outliers) == 1
    assert outliers[0].open_time == rows[2].open_time
    assert detect_price_jumps(rows[:2]) == []


async def test_record_issue_is_idempotent(session) -> None:
    for detail in ({"n": 1}, {"n": 2}):
        await record_issue(
            session,
            dataset="market.candle",
            scope_id="AAPL-USDT-SWAP:1h",
            kind="GAP",
            window_start=START,
            window_end=START + timedelta(hours=2),
            detail=detail,
        )
    await session.commit()

    issues = list(await session.scalars(select(DataQualityIssue)))
    assert len(issues) == 1
    assert issues[0].detail == {"n": 2}
    assert await session.scalar(select(func.count()).select_from(DataQualityIssue)) == 1


def test_coverage_bucket_locates_gap_window() -> None:
    actual = [START + timedelta(hours=hour) for hour in (0, 1, 4, 5)]
    buckets = coverage_by_day(actual, START, START + timedelta(hours=6), "1h")
    assert len(buckets) == 1
    bucket = buckets[0]
    assert bucket.expected == 6
    assert bucket.actual == 4
    assert bucket.missing == 2
    assert bucket.gaps == [(START + timedelta(hours=2), START + timedelta(hours=4))]

    summary = summarize(buckets)
    assert summary["expected"] == 6
    assert summary["actual"] == 4
    assert summary["ratio"] == 4 / 6

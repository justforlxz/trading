"""合约 K 线（AC3/AC8）：解析顺序、幂等回补、confirm 单调、缺口幂等与升序查询。"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

from sqlalchemy import func, select

from app.market.candles import (
    coverage,
    list_candles,
    record_gaps,
    upsert_candles,
)
from app.market.core.candles import duplicate_open_times, find_gaps, out_of_order
from app.market.models import Candle, DataQualityIssue
from tests.market.support import (
    fixture_candles,
    insert_instrument,
    make_candle_rows,
)


def test_recorded_series_is_sorted_and_complete() -> None:
    rows = fixture_candles("okx_aapl_1h.json", "1h")
    assert len(rows) == 300
    times = [row.open_time for row in rows]
    assert out_of_order(times) is False
    assert duplicate_open_times(times) == []
    assert all(row.bar == "1h" for row in rows)
    # 相邻两根间隔等于周期
    for previous, current in pairwise(rows):
        assert current.open_time - previous.open_time == timedelta(hours=1)


async def test_upsert_is_idempotent_and_keeps_single_copy(session) -> None:
    instrument = await insert_instrument(session)
    rows = fixture_candles()
    assert await upsert_candles(session, instrument.id, rows) == len(rows)
    assert await upsert_candles(session, instrument.id, rows) == len(rows)

    total = await session.scalar(
        select(func.count()).select_from(Candle).where(Candle.instrument_id == instrument.id)
    )
    assert total == len(rows)


async def test_confirmed_bar_is_not_overwritten_by_unconfirmed(session) -> None:
    instrument = await insert_instrument(session)
    start = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
    original = make_candle_rows(start=start, count=1, confirm_last=True)[0]
    await upsert_candles(session, instrument.id, [original])

    revised = replace(original, close=Decimal("999.0"), confirm=True)
    await upsert_candles(session, instrument.id, [revised])
    await upsert_candles(session, instrument.id, [original])

    stored = await session.scalar(
        select(Candle).where(Candle.instrument_id == instrument.id, Candle.bar == "1h")
    )
    assert stored is not None
    assert stored.confirm is True
    assert stored.close == Decimal("999.0")


async def test_gap_detection_is_idempotent(session) -> None:
    instrument = await insert_instrument(session)
    start = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
    rows = make_candle_rows(start=start, count=6)
    # 去掉第 3、4 根，制造一个连续缺口
    await upsert_candles(session, instrument.id, [rows[0], rows[1], rows[4], rows[5]])

    end = start + timedelta(hours=6)
    first = await record_gaps(session, instrument=instrument, bar="1h", start=start, end=end)
    second = await record_gaps(session, instrument=instrument, bar="1h", start=start, end=end)
    assert first == second
    assert first == [(start + timedelta(hours=2), start + timedelta(hours=4))]

    issues = list(
        await session.scalars(
            select(DataQualityIssue).where(
                DataQualityIssue.dataset == "market.candle",
                DataQualityIssue.scope_id == "AAPL-USDT-SWAP:1h",
                DataQualityIssue.kind == "GAP",
            )
        )
    )
    assert len(issues) == 1
    assert issues[0].window_start == start + timedelta(hours=2)


async def test_list_candles_is_strictly_ascending(session) -> None:
    instrument = await insert_instrument(session)
    rows = fixture_candles()
    await upsert_candles(session, instrument.id, rows)

    page, cursor = await list_candles(session, inst_id=instrument.inst_id, bar="1h", limit=10)
    assert len(page) == 10
    assert cursor is not None
    times = [row.open_time for row in page]
    assert times == sorted(times)
    assert len(set(times)) == len(times)
    for previous, current in pairwise(page):
        assert current.open_time - previous.open_time == timedelta(hours=1)

    tail, _ = await list_candles(
        session, inst_id=instrument.inst_id, bar="1h", limit=10, cursor=cursor
    )
    assert tail[0].open_time > page[-1].open_time


async def test_coverage_reports_expected_actual_and_gap_start(session) -> None:
    instrument = await insert_instrument(session)
    start = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
    day = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
    full_day = make_candle_rows(start=day, count=24)
    await upsert_candles(session, instrument.id, full_day[:20])

    result = await coverage(
        session, instrument=instrument, bar="1h", start=start, end=start + timedelta(days=1)
    )
    assert result["summary"]["expected"] == 24
    assert result["summary"]["actual"] == 20
    assert result["summary"]["missing"] == 4
    assert result["days"][0]["gaps"][0]["window_start"] == (day + timedelta(hours=20)).isoformat()


def test_find_gaps_merges_consecutive_missing_slots() -> None:
    start = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
    actual = {start, start + timedelta(hours=3)}
    assert find_gaps(actual, start, start + timedelta(hours=4), "1h") == [
        (start + timedelta(hours=1), start + timedelta(hours=3))
    ]

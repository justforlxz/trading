"""enrich 中间件：结算值与分钟级读数的时段判定。

结算值的 `ts` 就是该交易日的收盘时刻，天然属于「已收盘」，不需要查休市日表；日更源
可以回溯几十年，而休市日表只覆盖有限年份——混用会让整份历史结算数据在首次同步时被
日历判定拦住（QA 的 D1）。非结算时刻（分钟级）仍按日历判断，且日历缺年份时如实报错，
不猜一个「开市」出来。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core import Observation
from app.macro.pipeline import PendingBatch, Pipeline, enrich
from app.market import settlement_epoch

NINETEEN_NINETY = date(1990, 1, 2)


def _observation(ts: int) -> Observation:
    return Observation(
        series_id="vix",
        ts=ts,
        value=Decimal("17.24"),
        provider="cboe",
        is_delayed=False,
    )


def _capture(records: list) -> object:
    def middleware(batch: PendingBatch, call_next) -> None:
        records.extend(batch.records)
        call_next(batch)

    return middleware


def test_settlement_timestamp_needs_no_holiday_calendar() -> None:
    """1990 年的日结值不该被 2025–2027 的休市日表拦住。"""

    records: list = []
    batch = PendingBatch(observations=(_observation(settlement_epoch(NINETEEN_NINETY)),))

    outcome = Pipeline([enrich, _capture(records)]).run(batch)

    assert outcome.completed is True
    assert len(records) == 1
    assert records[0].trading_day == NINETEEN_NINETY
    assert records[0].market_session == "closed"


def test_minute_timestamp_outside_calendar_still_fails_fast() -> None:
    """分钟级读数依赖交易日历；日历缺年份时如实失败，不猜成「开市」。"""

    records: list = []
    # 17:00 ET 不是收盘时刻，走日历判定。
    batch = PendingBatch(observations=(_observation(settlement_epoch(NINETEEN_NINETY) + 3600),))

    outcome = Pipeline([enrich, _capture(records)]).run(batch)

    assert outcome.completed is False
    assert "1990" in (outcome.error or "")
    assert records == []


#: 2026-11-20 在休市日表覆盖范围内，可以用相邻秒验证「结算时刻」这一约定是严格相等。
IN_CALENDAR = date(2026, 11, 20)


@pytest.mark.parametrize(
    ("offset", "expected"),
    [(-1, "open"), (0, "closed"), (1, "closed")],
)
def test_settlement_boundary_is_exact(offset: int, expected: str) -> None:
    """收盘前一秒仍是开市，收盘那一刻与之后都算已收盘。"""

    records: list = []
    moment = settlement_epoch(IN_CALENDAR) + offset

    Pipeline([enrich, _capture(records)]).run(PendingBatch(observations=(_observation(moment),)))

    assert records[0].market_session == expected

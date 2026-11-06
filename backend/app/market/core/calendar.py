"""美股交易时段日历（纯函数，无第三方依赖）。

P1 只覆盖 XNYS（NYSE/Nasdaq 共用同一交易日历）。规则：

- 常规日：盘前 04:00–09:30，连续竞价 09:30–16:00，盘后 16:00–20:00（America/New_York）。
- 半日市：09:30–13:00，盘后顺延到 17:00；提前收盘日为感恩节次日、7/3、12/24
  （仅当它们是工作日且不是休市日）。
- 节假日：元旦、马丁·路德·金日、总统日、耶稣受难日、阵亡将士纪念日、Juneteenth、
  独立日、劳动节、感恩节、圣诞节；周六休市日前移到周五、周日休市日后移到周一。
- 临时休市（国葬、飓风等）单列在 `SPECIAL_CLOSURES`。
- 夏令时按美国规则（3 月第 2 个周日 02:00 起、11 月第 1 个周日 02:00 止）换算 UTC。

期望值由 `exchange_calendars`（dev-only 测试依赖）独立比对，见
`backend/tests/market/test_sessions.py`；被测函数不参与生成期望值。
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache

VENUE = "XNYS"
CALENDAR_SOURCE = "builtin:us-equity-v1"

STD_OFFSET_HOURS = 5  # EST (UTC-5)
DST_OFFSET_HOURS = 4  # EDT (UTC-4)

PRE_OPEN = time(4, 0)
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
HALF_DAY_CLOSE = time(13, 0)
POST_CLOSE = time(20, 0)
HALF_DAY_POST_CLOSE = time(17, 0)

# 纽交所/纳斯达克临时休市（国葬、飓风、恐袭等）。
SPECIAL_CLOSURES: frozenset[date] = frozenset(
    {
        date(2001, 9, 11),
        date(2001, 9, 12),
        date(2001, 9, 13),
        date(2001, 9, 14),
        date(2004, 6, 11),  # Reagan 国葬
        date(2007, 1, 2),  # Ford 国葬
        date(2012, 10, 29),  # Sandy
        date(2012, 10, 30),
        date(2018, 12, 5),  # G.H.W. Bush 国葬
        date(2025, 1, 9),  # Carter 国葬
    }
)


def easter_sunday(year: int) -> date:
    """Gregorian 复活节算法（Anonymous Gregorian algorithm）。"""

    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month, day = divmod(h + ell - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """某月第 n 个指定星期（weekday: Monday=0）。"""

    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """某月最后一个指定星期。"""

    last = date(year, 12, 31) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


def _observed(holiday: date) -> date:
    """周六休市前移到周五，周日休市后移到周一（NYSE 规则）。"""

    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


@lru_cache(maxsize=64)
def holidays(year: int) -> frozenset[date]:
    """某个自然年的 NYSE 休市日（含观测日规则与临时休市）。"""

    days = {
        _observed(date(year, 1, 1)),  # New Year's Day
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        easter_sunday(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed(date(year, 6, 19)),  # Juneteenth (2022 起)
        _observed(date(year, 7, 4)),  # Independence Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),  # Christmas
    }
    if year < 2022:
        days.discard(_observed(date(year, 6, 19)))
    if year < 1998:
        days.discard(_nth_weekday(year, 1, 0, 3))
    return frozenset(day for day in days if day.year == year) | frozenset(
        day for day in SPECIAL_CLOSURES if day.year == year
    )


def is_holiday(day: date) -> bool:
    return day in holidays(day.year)


def dst_start(year: int) -> date:
    """夏令时开始日（3 月第 2 个周日）。"""

    return _nth_weekday(year, 3, 6, 2)


def dst_end(year: int) -> date:
    """夏令时结束日（11 月第 1 个周日）。"""

    return _nth_weekday(year, 11, 6, 1)


def is_dst(day: date) -> bool:
    return dst_start(day.year) <= day < dst_end(day.year)


def utc_offset_hours(day: date) -> int:
    return DST_OFFSET_HOURS if is_dst(day) else STD_OFFSET_HOURS


def to_utc(day: date, local_time: time) -> datetime:
    """把纽约本地时间换成 UTC（盘前/盘后都在 04:00–20:00，不会落在切换空档）。"""

    offset = timedelta(hours=utc_offset_hours(day))
    naive = datetime.combine(day, local_time)
    return (naive + offset).replace(tzinfo=UTC)


@lru_cache(maxsize=64)
def early_closes(year: int) -> frozenset[date]:
    """提前到 13:00 收盘的日期。"""

    candidates = {
        _nth_weekday(year, 11, 3, 4) + timedelta(days=1),  # Thanksgiving 次日
        date(year, 7, 3),
        date(year, 12, 24),
    }
    closed = holidays(year)
    return frozenset(
        day for day in candidates if day.year == year and day.weekday() < 5 and day not in closed
    )


def is_trading_day(day: date) -> bool:
    """是否为交易日（工作日且非休市日）。"""

    return day.weekday() < 5 and not is_holiday(day)


@dataclass(frozen=True, slots=True)
class SessionWindow:
    """一个自然日的交易时段边界（全部 UTC；非交易日为 None）。"""

    trading_date: date
    is_session: bool
    is_half_day: bool
    is_holiday: bool
    pre_start: datetime | None = None
    pre_end: datetime | None = None
    regular_start: datetime | None = None
    regular_end: datetime | None = None
    post_start: datetime | None = None
    post_end: datetime | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "venue": VENUE,
            "trading_date": self.trading_date.isoformat(),
            "is_session": self.is_session,
            "is_half_day": self.is_half_day,
            "is_holiday": self.is_holiday,
            "pre_start": self.pre_start,
            "pre_end": self.pre_end,
            "regular_start": self.regular_start,
            "regular_end": self.regular_end,
            "post_start": self.post_start,
            "post_end": self.post_end,
            "calendar_source": CALENDAR_SOURCE,
        }


def session_window(day: date) -> SessionWindow:
    """生成某一天的交易时段；周末/休市日返回 is_session=False。"""

    if day.weekday() >= 5:
        return SessionWindow(day, False, False, False)
    if is_holiday(day):
        return SessionWindow(day, False, False, True)

    half_day = day in early_closes(day.year)
    regular_close = HALF_DAY_CLOSE if half_day else REGULAR_CLOSE
    post_close = HALF_DAY_POST_CLOSE if half_day else POST_CLOSE
    pre_start = to_utc(day, PRE_OPEN)
    regular_start = to_utc(day, REGULAR_OPEN)
    regular_end = to_utc(day, regular_close)
    post_end = to_utc(day, post_close)
    return SessionWindow(
        trading_date=day,
        is_session=True,
        is_half_day=half_day,
        is_holiday=False,
        pre_start=pre_start,
        pre_end=regular_start,
        regular_start=regular_start,
        regular_end=regular_end,
        post_start=regular_end,
        post_end=post_end,
    )


def iter_sessions(start: date, end: date) -> list[SessionWindow]:
    """按自然日枚举 `[start, end]`（含首尾）内的时段表。"""

    if end < start:
        raise ValueError("end must be on or after start")
    days = (end - start).days
    return [session_window(start + timedelta(days=i)) for i in range(days + 1)]


def session_phase(ts: datetime) -> str:
    """把一个 UTC 时间点归入 PRE / REGULAR / POST / CLOSED。"""

    if ts.tzinfo is None:
        raise ValueError("ts must be timezone-aware")
    utc = ts.astimezone(UTC)
    # 两个可能的本地偏移各试一次：夏令时切换当天也不会把边界算错。
    for offset_hours in (DST_OFFSET_HOURS, STD_OFFSET_HOURS):
        local = utc - timedelta(hours=offset_hours)
        window = session_window(local.date())
        if window.is_session:
            if window.pre_start <= utc < window.pre_end:  # type: ignore[operator]
                return "PRE"
            if window.regular_start <= utc < window.regular_end:  # type: ignore[operator]
                return "REGULAR"
            if window.post_start <= utc < window.post_end:  # type: ignore[operator]
                return "POST"
    return "CLOSED"


def trading_days(start: date, end: date) -> list[date]:
    """区间内的交易日（用于覆盖率分母）。"""

    return [w.trading_date for w in iter_sessions(start, end) if w.is_session]


def previous_trading_day(day: date) -> date:
    """上一个交易日（回补窗口起点用）。"""

    cursor = day - timedelta(days=1)
    while not is_trading_day(cursor):
        cursor -= timedelta(days=1)
    return cursor

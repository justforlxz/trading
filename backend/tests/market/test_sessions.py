"""交易日历（AC7）：DST、半日市、节假日，并用 exchange_calendars 做独立 oracle。"""

from datetime import UTC, date, datetime, timedelta

from exchange_calendars import get_calendar

from app.market.core.calendar import iter_sessions, session_phase, session_window


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def test_dst_switch_shifts_regular_session_by_one_hour() -> None:
    before = session_window(date(2026, 3, 6))
    after = session_window(date(2026, 3, 9))
    assert before.is_session and after.is_session
    assert before.regular_start == _utc(2026, 3, 6, 14, 30)
    assert before.regular_end == _utc(2026, 3, 6, 21, 0)
    assert after.regular_start == _utc(2026, 3, 9, 13, 30)
    assert after.regular_end == _utc(2026, 3, 9, 20, 0)


def test_thanksgiving_and_half_day() -> None:
    thanksgiving = session_window(date(2026, 11, 26))
    assert thanksgiving.is_session is False
    assert thanksgiving.is_holiday is True

    half_day = session_window(date(2026, 11, 27))
    assert half_day.is_session is True
    assert half_day.is_half_day is True
    assert half_day.regular_start == _utc(2026, 11, 27, 14, 30)
    assert half_day.regular_end == _utc(2026, 11, 27, 18, 0)
    assert half_day.post_end == _utc(2026, 11, 27, 22, 0)


def test_weekend_is_not_a_session() -> None:
    saturday = session_window(date(2026, 3, 7))
    assert saturday.is_session is False
    assert saturday.regular_start is None


def test_session_phase_covers_four_states() -> None:
    assert session_phase(_utc(2026, 3, 9, 12, 0)) == "PRE"
    assert session_phase(_utc(2026, 3, 9, 14, 0)) == "REGULAR"
    assert session_phase(_utc(2026, 3, 9, 21, 0)) == "POST"
    assert session_phase(_utc(2026, 3, 9, 2, 0)) == "CLOSED"


def test_daily_calendar_matches_exchange_calendars_oracle() -> None:
    """逐日比对 2024-01-01..2026-12-31：期望值来自独立实现，不由被测函数推导。"""

    oracle = get_calendar("XNYS", start="2024-01-02", end="2026-12-31")
    labels = {label.date(): label for label in oracle.sessions_in_range("2024-01-02", "2026-12-31")}
    early_closes = {label.date() for label in oracle.early_closes}

    day = date(2024, 1, 2)
    last = date(2026, 12, 31)
    while day <= last:
        window = session_window(day)
        label = labels.get(day)
        assert window.is_session is (label is not None), f"is_session mismatch on {day}"
        if label is not None:
            assert window.regular_start == oracle.session_open(label).to_pydatetime(), day
            assert window.regular_end == oracle.session_close(label).to_pydatetime(), day
            assert window.is_half_day is (day in early_closes), f"half day mismatch on {day}"
        day += timedelta(days=1)
    assert len(labels) > 700


def test_iter_sessions_covers_every_calendar_day() -> None:
    windows = list(iter_sessions(date(2026, 11, 25), date(2026, 11, 29)))
    assert [window.trading_date for window in windows] == [
        date(2026, 11, 25),
        date(2026, 11, 26),
        date(2026, 11, 27),
        date(2026, 11, 28),
        date(2026, 11, 29),
    ]
    assert [window.is_session for window in windows] == [True, False, True, False, False]

"""权益曲线：区间覆盖不足时不给点，绝不插值。

`account_snapshots` 只有十天数据时，「1 月」窗口画出来是一条被截断的线，会让人以为
那十天就是一个月。这里断言两种输出：`available=True` 且带点，或者 `available=False`
且 `points` 为空——没有第三种（画半截）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core import AccountSnapshot, ExchangePosition
from app.positions import record_exchange_snapshot
from app.positions.curves import (
    CURVE_RANGES,
    MAX_EQUITY_POINTS,
    CurvePoint,
    _downsample,
    equity_curve,
    upl_curves,
)

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def _snapshot(equity: str) -> AccountSnapshot:
    return AccountSnapshot(
        currency="USDT",
        equity=Decimal(equity),
        available_equity=Decimal(equity),
        cash_balance=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        used_margin=Decimal("0"),
        available_margin=Decimal(equity),
        margin_ratio=Decimal("0"),
    )


def _write_equity_history(*, span: timedelta, step: timedelta = timedelta(minutes=30)) -> None:
    """以 `NOW` 为终点往前写一串快照，覆盖 `span` 那么长的时间。"""

    moment = NOW - span
    index = 0
    while moment <= NOW:
        record_exchange_snapshot(
            captured_at=moment,
            source="okx_rest",
            snapshot=_snapshot(str(400 + index)),
        )
        moment += step
        index += 1


def test_one_day_curve_is_available_and_has_points(client: TestClient) -> None:
    _write_equity_history(span=timedelta(days=1), step=timedelta(hours=1))

    curve = equity_curve("1d", now=NOW)

    assert curve.available is True
    assert len(curve.points) >= 2
    assert curve.points[-1].at <= NOW
    assert curve.first_snapshot_at is not None


def test_one_month_curve_has_no_points_when_only_ten_days_exist(client: TestClient) -> None:
    """十天数据撑不了一个月：返回空点集，让界面显示「数据不足」。"""

    _write_equity_history(span=timedelta(days=10), step=timedelta(hours=6))

    curve = equity_curve("1m", now=NOW)

    assert curve.available is False
    assert curve.points == ()
    assert curve.first_snapshot_at == NOW - timedelta(days=10)


def test_six_month_and_one_year_are_also_unavailable_on_ten_days(client: TestClient) -> None:
    _write_equity_history(span=timedelta(days=10), step=timedelta(hours=6))

    for key in ("6m", "1y"):
        assert equity_curve(key, now=NOW).points == ()


def test_empty_history_reports_unavailable_without_a_first_snapshot(
    client: TestClient,
) -> None:
    curve = equity_curve("1d", now=NOW)

    assert curve.available is False
    assert curve.points == ()
    assert curve.first_snapshot_at is None


def test_curve_is_downsampled_but_keeps_the_ends() -> None:
    points = tuple(
        CurvePoint(NOW + timedelta(minutes=index), Decimal(index)) for index in range(400)
    )

    sampled = _downsample(points, MAX_EQUITY_POINTS)

    assert len(sampled) == MAX_EQUITY_POINTS
    assert sampled[0] == points[0]
    assert sampled[-1] == points[-1]


def test_upl_curve_without_two_points_is_dropped(client: TestClient) -> None:
    """单点画不出曲线，一条水平假线比空着更糟。"""

    record_exchange_snapshot(
        captured_at=NOW,
        source="okx_rest",
        snapshot=_snapshot("400"),
        positions=[
            _position("pos-1", upl="5"),
        ],
    )

    assert upl_curves("1d", now=NOW) == {}


def _position(pos_id: str, *, upl: str) -> ExchangePosition:
    return ExchangePosition(
        pos_id=pos_id,
        inst_id="AAPL-USDT-SWAP",
        pos_side="long",
        size=Decimal("1"),
        avg_px=Decimal("100"),
        mark_px=Decimal("100"),
        upl=Decimal(upl),
        upl_ratio=Decimal("0"),
        lever=Decimal("3"),
        mgn_mode="isolated",
        liq_px=None,
        margin=Decimal("0"),
    )


def test_ranges_cover_the_five_buttons() -> None:
    assert list(CURVE_RANGES) == ["1d", "1w", "1m", "6m", "1y"]

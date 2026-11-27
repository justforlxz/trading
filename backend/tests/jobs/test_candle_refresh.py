"""K 线刷新：只补过期周期、按周期限流、有持仓与自选都算在内。

MKACG-1019 的根因是 OKX 的 K 线只在用户点开标的时才同步，持仓卡片因此读到 8 天前的
收盘价。本文件钉住补数据的判据：

- 缺口按「最新一根 K 线什么时候收盘」算，不看标的类别与前缀；
- 一个周期还没收盘就不提交，刚更新过的序列不被反复拉取；
- 同一个 `(标的, 周期)` 每个周期最多尝试一次，上游故障不会变成每分钟一条失败流水；
- 有持仓的标的与自选都算「价格还在被人用」，没有队列时整步跳过；
- 刷新窗口按缺口算，不会因为一个很久以前的缺口就重新拉 400 天。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core import AccountSnapshot, Bar, ExchangePosition, Timeframe
from app.exchange.okx.instruments import parse_instruments
from app.instrument import sync_instruments
from app.jobs import (
    DEFAULT_DAYS_BY_BAR,
    MAX_REFRESH_DAYS,
    SETTLE_GRACE,
    refresh_due,
    run_candle_refresh,
)
from app.market import upsert_candles
from app.positions import record_exchange_snapshot
from app.watchlist import add_item
from tests.exchange.conftest import SPOT_INSTRUMENT, SWAP_INSTRUMENT
from tests.fakes.on_demand import RecordingScheduler

NOW = datetime(2026, 11, 27, 6, 0, tzinfo=UTC)
SPOT_INST_ID = "XAAPL-USDT"
SWAP_INST_ID = "AAPL-USDT-SWAP"


def test_refresh_due_fills_an_empty_series_with_the_default_window() -> None:
    # 一根 K 线都没有：按该周期平时的回看窗口补一次，日内周期不跟着拉 400 天。
    assert refresh_due(None, NOW, "1d") == DEFAULT_DAYS_BY_BAR["1d"]
    assert refresh_due(None, NOW, "1h") == DEFAULT_DAYS_BY_BAR["1h"]


def test_refresh_due_waits_two_periods_because_the_next_bar_needs_its_whole_period() -> None:
    # 库里最后一根 1h K 线开盘于 05:00（06:00 收盘）。紧接的那根 06:00 要到 07:00 才收盘，
    # 因此在 07:00 之前重拉只能拿到同一根，白打一次上游。
    latest = datetime(2026, 11, 27, 5, 0, tzinfo=UTC)
    assert refresh_due(latest, latest + timedelta(minutes=30), "1h") is None
    assert refresh_due(latest, latest + timedelta(hours=1), "1h") is None
    assert refresh_due(latest, latest + timedelta(hours=2), "1h") is None
    assert refresh_due(latest, latest + timedelta(hours=2) + SETTLE_GRACE, "1h") is not None


def test_refresh_due_covers_the_gap_but_never_reloads_full_history() -> None:
    # 8 天前的日线：回看 9 天覆盖缺口（8 天 + 1 天余量），而不是 400 天。
    stale = NOW - timedelta(days=8)
    assert refresh_due(stale, NOW, "1d") == 9
    # 缺口再长也不把窗口放大：更久的历史交给用户点开标的时的全量同步。
    ancient = NOW - timedelta(days=400)
    assert refresh_due(ancient, NOW, "1d") == MAX_REFRESH_DAYS


@pytest.fixture()
def instruments(job_schema: None) -> None:
    sync_instruments(parse_instruments([SPOT_INSTRUMENT, SWAP_INSTRUMENT]))


def _candle(inst_id: str, bar: str, open_time: datetime, close: str = "352.99") -> Bar:
    return Bar(
        inst_id=inst_id,
        timeframe=Timeframe.parse(bar),
        open_time=open_time,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=Decimal("1"),
        confirm=True,
        source="okx_spot",
    )


def _hold(inst_id: str, captured_at: datetime = NOW - timedelta(minutes=5)) -> None:
    """写一份「手里有这个标的」的持仓快照；刷新拿它拼出要维持新鲜的集合。"""

    record_exchange_snapshot(
        captured_at=captured_at,
        source="okx_rest",
        snapshot=AccountSnapshot(
            currency="USDT",
            equity=Decimal("1000"),
            available_equity=Decimal("600"),
            cash_balance=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            used_margin=Decimal("0"),
            available_margin=Decimal("600"),
            margin_ratio=Decimal("0"),
        ),
        positions=[
            ExchangePosition(
                pos_id=f"{inst_id}:long",
                inst_id=inst_id,
                pos_side="long",
                size=Decimal("1"),
                avg_px=Decimal("300"),
                mark_px=None,
                upl=None,
                upl_ratio=None,
                lever=None,
                mgn_mode=None,
                liq_px=None,
                margin=None,
            )
        ],
        stops=[],
        stops_available=True,
    )


def test_stale_candles_of_a_held_instrument_are_submitted(instruments: None) -> None:
    """AC2：有持仓的标的停更 8 天，1d 与 1h 都要补，且按缺口算窗口。"""

    upsert_candles([_candle(SPOT_INST_ID, "1d", NOW - timedelta(days=8))])
    _hold(SPOT_INST_ID)
    scheduler = RecordingScheduler()

    submitted = run_candle_refresh(scheduler, clock=_fixed(NOW), attempted={})

    assert {(target.symbol, target.bar) for target in submitted} == {
        (SPOT_INST_ID, "1d"),
        (SPOT_INST_ID, "1h"),
    }
    # 1h 一根都没有 → 按默认窗口补；1d 有 8 天缺口 → 按缺口补。
    assert scheduler.calls == [
        (SPOT_INST_ID, "1d", 9),
        (SPOT_INST_ID, "1h", DEFAULT_DAYS_BY_BAR["1h"]),
    ]


def test_watchlist_instruments_are_refreshed_but_fresh_bars_are_not(instruments: None) -> None:
    """自选也算「价格还在被人用」；刚更新的日线不重复拉。"""

    add_item(SWAP_INST_ID)
    upsert_candles(
        [
            _candle(SWAP_INST_ID, "1d", NOW - timedelta(hours=12)),
            _candle(SWAP_INST_ID, "1h", NOW - timedelta(minutes=1)),
        ]
    )
    scheduler = RecordingScheduler()

    submitted = run_candle_refresh(scheduler, clock=_fixed(NOW), attempted={})

    assert submitted == ()
    assert scheduler.calls == []


def test_a_period_is_attempted_at_most_once_per_bar(instruments: None) -> None:
    """同一 `(标的, 周期)` 在下一个周期到来前不再提交，故障不会变成刷屏流水。"""

    _hold(SPOT_INST_ID)
    scheduler = RecordingScheduler()
    attempted: dict[tuple[str, str], datetime] = {}

    first = run_candle_refresh(scheduler, clock=_fixed(NOW), attempted=attempted)
    # 一分钟后上游仍然失败、K 线仍然没推进：不再提交。
    later = run_candle_refresh(
        scheduler, clock=_fixed(NOW + timedelta(minutes=1)), attempted=attempted
    )

    assert first != ()
    assert later == ()
    assert len(scheduler.calls) == len(first)


def test_a_missing_scheduler_skips_the_step(instruments: None) -> None:
    """没有按需同步队列时刷新不成立，也不抛错拖垮调度轮次。"""

    _hold(SPOT_INST_ID)

    assert run_candle_refresh(None, clock=_fixed(NOW), attempted={}) == ()


class _FixedClock:
    """固定时刻的时钟：过期判定与尝试记忆都用同一个时间，不跨时钟。"""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


def _fixed(moment: datetime) -> _FixedClock:
    return _FixedClock(moment)

"""假 OKX 数据源：标的计数、K 线游标、收盘标记与参数校验。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.exchange import ExchangeError
from app.exchange.okx.instruments import parse_instruments
from tests.factories.instruments import make_instrument_row
from tests.fakes.okx.store import (
    INVALID_PARAMETER_CODE,
    UNKNOWN_INST_ID_CODE,
    OkxApiError,
    OkxStore,
)

# 2026-11-10T12:00:00Z：固定时钟让 K 线边界可预期。
FIXED_NOW = 1794312000
SPOT_ID = "XAAPL-USDT"


@pytest.fixture()
def store() -> OkxStore:
    return OkxStore(clock=lambda: float(FIXED_NOW))


def test_spot_instruments_only_include_live_tokenized_equities(store: OkxStore) -> None:
    rows = store.instruments("SPOT")

    assert len(rows) == 199
    assert {row["instType"] for row in rows} == {"SPOT"}
    assert {row["instCategory"] for row in rows} == {"3"}
    assert {row["state"] for row in rows} == {"live"}


def test_swap_instruments_cover_the_full_contract_set(store: OkxStore) -> None:
    rows = store.instruments("SWAP")

    assert len(rows) == 230
    assert {row["instType"] for row in rows} == {"SWAP"}
    assert {row["instCategory"] for row in rows} == {"3"}


def test_unknown_inst_type_is_a_business_error(store: OkxStore) -> None:
    with pytest.raises(OkxApiError) as caught:
        store.instruments("FUTURES")

    assert caught.value.code == INVALID_PARAMETER_CODE


def test_candles_are_newest_first_with_only_the_head_unclosed(store: OkxStore) -> None:
    rows = store.candles(SPOT_ID, "1D", 5)

    assert len(rows) == 5
    timestamps = [int(row[0]) for row in rows]
    assert timestamps == sorted(timestamps, reverse=True)
    assert rows[0][8] == "0"
    assert [row[8] for row in rows[1:]] == ["1"] * 4


def test_daily_bars_open_at_sixteen_utc(store: OkxStore) -> None:
    for row in store.candles(SPOT_ID, "1D", 10):
        assert int(row[0]) // 1000 % 86400 == 57600


def test_intraday_bars_are_aligned_to_their_period(store: OkxStore) -> None:
    seconds = {"1m": 60, "15m": 900, "1H": 3600, "4H": 14400}

    for bar, period in seconds.items():
        for row in store.candles(SPOT_ID, bar, 4):
            assert int(row[0]) // 1000 % period == 0


def test_candle_prices_form_a_valid_ohlc(store: OkxStore) -> None:
    for row in store.candles(SPOT_ID, "1H", 8):
        open_price, high, low, close = (Decimal(value) for value in row[1:5])
        assert high >= max(open_price, close)
        assert low <= min(open_price, close)
        assert Decimal(row[5]) > 0


def test_candle_prices_are_deterministic_across_stores() -> None:
    first = OkxStore(clock=lambda: float(FIXED_NOW)).candles(SPOT_ID, "1H", 3)
    second = OkxStore(clock=lambda: float(FIXED_NOW)).candles(SPOT_ID, "1H", 3)

    assert first == second


def test_history_cursor_returns_strictly_older_closed_bars(store: OkxStore) -> None:
    page = store.candles(SPOT_ID, "1H", 10)
    cursor = int(page[-1][0]) // 1000

    older = store.history_candles(SPOT_ID, "1H", after=cursor, limit=10)

    assert older
    assert all(int(row[0]) // 1000 < cursor for row in older)
    assert {row[8] for row in older} == {"1"}


def test_history_cursor_pages_without_gap_or_overlap(store: OkxStore) -> None:
    first = store.candles(SPOT_ID, "1H", 5)
    second = store.history_candles(SPOT_ID, "1H", after=int(first[-1][0]) // 1000, limit=5)

    assert int(second[0][0]) == int(first[-1][0]) - 3600 * 1000
    assert set(int(row[0]) for row in first).isdisjoint(int(row[0]) for row in second)


def test_history_without_cursor_matches_recent_candles(store: OkxStore) -> None:
    assert store.history_candles(SPOT_ID, "1H", limit=5) == store.candles(SPOT_ID, "1H", 5)


@pytest.mark.parametrize("limit", [0, 101])
def test_limit_outside_upstream_range_is_rejected(store: OkxStore, limit: int) -> None:
    with pytest.raises(OkxApiError) as caught:
        store.candles(SPOT_ID, "1H", limit)

    assert caught.value.code == INVALID_PARAMETER_CODE


def test_unknown_bar_is_rejected(store: OkxStore) -> None:
    with pytest.raises(OkxApiError) as caught:
        store.candles(SPOT_ID, "2H", 5)

    assert caught.value.code == INVALID_PARAMETER_CODE


def test_unknown_inst_id_is_rejected(store: OkxStore) -> None:
    with pytest.raises(OkxApiError) as caught:
        store.candles("XNOTREAL-USDT", "1H", 5)

    assert caught.value.code == UNKNOWN_INST_ID_CODE


def test_ticker_carries_upstream_field_names(store: OkxStore) -> None:
    row = store.ticker(SPOT_ID)

    assert row["instId"] == SPOT_ID
    assert row["instType"] == "SPOT"
    assert row["ts"] == str(FIXED_NOW * 1000)
    assert Decimal(row["bidPx"]) < Decimal(row["last"]) < Decimal(row["askPx"])


def test_store_passes_degraded_preopen_row_through_verbatim() -> None:
    """上游真实存在精度为空串的 preopen 行；fake 原样透传，适配器须容忍不崩。"""

    degraded = make_instrument_row(
        instId="XORCL-USDC",
        baseCcy="XORCL",
        quoteCcy="USDC",
        tickSz="",
        lotSz="",
        minSz="",
        state="preopen",
    )

    rows = OkxStore(instruments=[degraded]).instruments("SPOT")

    assert rows == [degraded]
    (info,) = parse_instruments(rows)
    assert info.inst_id == "XORCL-USDC"
    assert info.state == "preopen"
    assert info.tick_size is None
    assert info.lot_size is None
    assert info.min_size is None


def test_store_can_drive_adapter_rejection_of_invalid_metadata() -> None:
    """非空但非法的精度必须继续让整批解析失败，fake 保留该错误通道。"""

    broken = make_instrument_row(tickSz="abc")
    rows = OkxStore(instruments=[broken]).instruments("SPOT")

    assert rows == [broken]
    with pytest.raises(ExchangeError) as caught:
        parse_instruments(rows)
    assert "标的元数据数值非法" in str(caught.value)

"""历史 K 线同步：分页、窗口过滤、只写已收盘、幂等落库。

拓扑固定：真实 `OkxMarketData` → 线程内假 OKX → 临时 SQLite。
期望值全部由窗口与周期反推，不依赖上游返回顺序。
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event, text

from app.core import Bar, Timeframe, ValidationError
from app.db import session_scope
from app.db.engine import get_engine
from app.exchange import ExchangeError, create_market_data
from app.market import (
    data_range,
    expected_open_times,
    load_candles,
    sync_candles,
    upsert_candles,
)
from app.market import sync as sync_module

SYMBOL = "XAAPL-USDT"
DAILY_END = datetime(2026, 11, 6, 16, 0, tzinfo=UTC)


def _bar(
    open_time: datetime,
    *,
    confirm: bool = True,
    bar: str = "1h",
    symbol: str = SYMBOL,
    close: Decimal | None = None,
) -> Bar:
    return Bar(
        inst_id=symbol,
        timeframe=Timeframe.parse(bar),
        open_time=open_time,
        open=Decimal("10.00"),
        high=Decimal("11.00"),
        low=Decimal("9.00"),
        close=Decimal("10.50") if close is None else close,
        volume=Decimal("100.00"),
        confirm=confirm,
        source="okx",
    )


# ------------------------------------------------------------------ 分页下载


def test_sync_pages_back_until_it_covers_the_window(market_port) -> None:
    start = DAILY_END - timedelta(hours=250)
    result = sync_candles(market_port, SYMBOL, "1h", start, DAILY_END, inst_type="SPOT")

    # 250 根按每页 100 根往回翻，需要 3 页。
    assert result.pages == 3
    assert result.downloaded == 250
    assert result.inserted == 250
    assert result.updated == 0
    assert result.skipped_unconfirmed == 0

    bars = load_candles(SYMBOL, "1h", start=start, end=DAILY_END)
    assert [bar.open_time for bar in bars] == expected_open_times(start, DAILY_END, "1h")
    assert all(start <= bar.open_time < DAILY_END for bar in bars)


def test_sync_downloads_exactly_the_requested_window(market_port) -> None:
    """上游能给出更早数据时也要停在窗口边界，不越界多取。"""

    start = DAILY_END - timedelta(days=30)
    result = sync_candles(market_port, SYMBOL, "1d", start, DAILY_END, inst_type="SPOT")

    assert result.pages == 1
    assert result.downloaded == 30
    assert data_range(SYMBOL, "1d") == (start, DAILY_END - timedelta(days=1))


def test_sync_handles_a_window_larger_than_one_write_batch(market_port) -> None:
    """3 天 1 分钟线共 4320 行，超过默认构建单条 INSERT 的绑定参数上限。"""

    start = DAILY_END - timedelta(days=3)
    result = sync_candles(market_port, SYMBOL, "1m", start, DAILY_END, inst_type="SPOT")

    assert result.pages == 44
    assert result.downloaded == 4320
    assert result.inserted == 4320
    assert len(load_candles(SYMBOL, "1m")) == 4320


# ------------------------------------------------------------------- 幂等性


def test_syncing_the_same_batch_twice_does_not_add_rows(market_port) -> None:
    start = DAILY_END - timedelta(hours=12)
    first = sync_candles(market_port, SYMBOL, "1h", start, DAILY_END, inst_type="SPOT")
    second = sync_candles(market_port, SYMBOL, "1h", start, DAILY_END, inst_type="SPOT")

    assert first.inserted == 12
    assert (second.inserted, second.updated) == (0, 12)
    assert len(load_candles(SYMBOL, "1h")) == 12


def test_upsert_skips_unconfirmed_and_keeps_exact_decimals() -> None:
    moment = DAILY_END - timedelta(hours=2)
    pending = _bar(DAILY_END - timedelta(hours=1), confirm=False)
    price = Decimal("123.456789012345678901")

    result = upsert_candles([_bar(moment, close=price), pending])

    assert (result.inserted, result.updated, result.skipped_unconfirmed) == (1, 0, 1)
    stored = load_candles(SYMBOL, "1h")
    assert [bar.open_time for bar in stored] == [moment]
    assert stored[0].close == price
    assert data_range(SYMBOL, "1h") == (moment, moment)


def test_upsert_overwrites_prices_without_changing_row_count() -> None:
    moment = DAILY_END - timedelta(hours=2)

    upsert_candles([_bar(moment, close=Decimal("10.00"))])
    result = upsert_candles([_bar(moment, close=Decimal("20.00"))])

    assert (result.inserted, result.updated) == (0, 1)
    assert [bar.close for bar in load_candles(SYMBOL, "1h")] == [Decimal("20.00")]


def test_upsert_splits_writes_beyond_the_sqlite_parameter_limit() -> None:
    """4320 行 × 10 个绑定值远超默认上限 32766，必须切块写入而不是整体失败。"""

    start = DAILY_END - timedelta(days=3)
    bars = [_bar(start + timedelta(minutes=offset), bar="1m") for offset in range(4320)]

    first = upsert_candles(bars)
    second = upsert_candles(bars)

    assert (first.inserted, first.updated) == (4320, 0)
    assert (second.inserted, second.updated) == (0, 4320)
    assert len(load_candles(SYMBOL, "1m")) == 4320


def test_upsert_counts_unique_keys_when_a_batch_repeats() -> None:
    start = DAILY_END - timedelta(hours=5)
    bars = [_bar(start + timedelta(hours=offset)) for offset in range(5)]

    result = upsert_candles([*bars, bars[0]])

    assert (result.inserted, result.updated) == (5, 0)
    assert len(load_candles(SYMBOL, "1h")) == 5


def test_upsert_splits_statements_when_the_variable_limit_is_low(monkeypatch) -> None:
    """按批大小收紧 SQLite 变量上限：单条写入整批必失败，切块才能写进去。

    真实构建的上限（32766）在本机被抬到 250000，只有收紧上限才能稳定证明切块生效。
    """

    monkeypatch.setattr(sync_module, "UPSERT_BATCH_SIZE", 4)
    variable_limit = 10 * sync_module.UPSERT_BATCH_SIZE

    engine = get_engine()
    engine.dispose()

    @event.listens_for(engine, "connect")
    def _cap_variables(connection, _record) -> None:
        connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, variable_limit)

    start = DAILY_END - timedelta(hours=20)
    bars = [_bar(start + timedelta(hours=offset)) for offset in range(20)]

    result = upsert_candles(bars)

    assert result.inserted == 20
    assert len(load_candles(SYMBOL, "1h")) == 20


# ------------------------------------------------------------- 日线边界（UTC+8）


def test_daily_bars_are_stored_on_the_utc8_boundary(market_port) -> None:
    start = DAILY_END - timedelta(days=5)
    sync_candles(market_port, SYMBOL, "1d", start, DAILY_END, inst_type="SPOT")

    with session_scope() as session:
        canonical = session.execute(
            text("SELECT COUNT(*) FROM candles WHERE bar = '1d' AND open_time % 86400 != 57600")
        ).scalar_one()
        rows = session.execute(text("SELECT COUNT(*) FROM candles WHERE bar = '1d'")).scalar_one()
        raw_uppercase = session.execute(
            text("SELECT COUNT(*) FROM candles WHERE bar = '1D'")
        ).scalar_one()

    assert rows == 5
    assert canonical == 0
    # 上游写法不落库：适配层已经把 1D 映射成规范 1d。
    assert raw_uppercase == 0


# --------------------------------------------------------------------- 错误路径


@pytest.mark.parametrize(
    ("bar", "start", "end", "page_limit"),
    [
        ("2h", DAILY_END - timedelta(hours=3), DAILY_END, 100),
        ("1h", DAILY_END, DAILY_END, 100),
        ("1h", DAILY_END, DAILY_END - timedelta(hours=1), 100),
        ("1h", DAILY_END - timedelta(hours=3), DAILY_END, 0),
        ("1h", DAILY_END - timedelta(hours=3), DAILY_END, 101),
    ],
)
def test_sync_rejects_invalid_arguments(market_port, bar, start, end, page_limit) -> None:
    with pytest.raises(ValidationError):
        sync_candles(market_port, SYMBOL, bar, start, end, inst_type="SPOT", page_limit=page_limit)


def test_sync_rejects_naive_datetimes(market_port) -> None:
    with pytest.raises(ValidationError):
        sync_candles(
            market_port,
            SYMBOL,
            "1h",
            datetime(2026, 11, 6),  # 故意构造无时区时间
            DAILY_END,
            inst_type="SPOT",
        )


def test_sync_propagates_upstream_failure_and_writes_nothing(
    fake_okx_settings, fake_okx_server
) -> None:
    fake_okx_server.scenarios.activate("upstream_error")
    port = create_market_data(settings=fake_okx_settings)
    try:
        with pytest.raises(ExchangeError):
            sync_candles(
                port, SYMBOL, "1h", DAILY_END - timedelta(hours=3), DAILY_END, inst_type="SPOT"
            )
    finally:
        port.close()

    assert load_candles(SYMBOL, "1h") == []

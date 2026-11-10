"""自选域行为：分组增删、行情快照口径、价格提醒、相关标的排序。

期望值都由「库里写了哪几根日线」反推：`last_price` 取最新收盘，
`change_pct_24h` 是相邻两根收盘的涨跌幅，`volume_24h_quote` 是收盘 × 成交量。
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core import Bar, DataUnavailable, Timeframe, ValidationError
from app.instrument import sync_instruments
from app.market import upsert_candles
from app.watchlist import (
    add_item,
    clear_alert,
    list_entries,
    list_groups,
    move_item,
    related_instruments,
    remove_item,
    set_alert,
)
from tests.factories.instruments import make_ref, make_swap_ref

DAY = timedelta(days=1)
START = datetime(2026, 10, 1, 16, 0, tzinfo=UTC)


def _seed_instruments(*refs) -> None:
    sync_instruments(list(refs))


def _daily(symbol: str, closes: list[str], *, volume: str = "10") -> None:
    """写入连续日线（每天 16:00 UTC 开盘），收盘价按入参给定。"""

    upsert_candles(
        [
            Bar(
                inst_id=symbol,
                timeframe=Timeframe.parse("1d"),
                open_time=START + DAY * index,
                open=Decimal(close),
                high=Decimal(close),
                low=Decimal(close),
                close=Decimal(close),
                volume=Decimal(volume),
                confirm=True,
                source="okx",
            )
            for index, close in enumerate(closes)
        ]
    )


def test_add_item_returns_entry_with_quote_from_daily_candles() -> None:
    _seed_instruments(make_ref())
    _daily("XAAPL-USDT", ["100", "110"])

    entry = add_item("XAAPL-USDT")

    assert entry is not None
    assert entry.group == "默认"
    assert entry.quote.last_price == Decimal("110")
    assert entry.quote.change_pct_24h == Decimal("10.000000")
    assert entry.quote.volume_24h_quote == Decimal("1100.00")
    assert entry.alert is None
    assert list_groups() == ["默认"]


def test_add_item_unknown_symbol_returns_none() -> None:
    assert add_item("UNKNOWN-USDT") is None
    assert list_entries() == []


def test_add_item_without_daily_candles_reports_missing_data() -> None:
    _seed_instruments(make_ref())
    _daily("XAAPL-USDT", ["100"])

    with pytest.raises(DataUnavailable):
        add_item("XAAPL-USDT")

    # 行情算不出来就不留半条自选。
    assert list_entries() == []
    assert list_groups() == []


def test_add_item_twice_is_rejected() -> None:
    _seed_instruments(make_ref())
    _daily("XAAPL-USDT", ["100", "110"])
    assert add_item("XAAPL-USDT") is not None

    with pytest.raises(ValidationError):
        add_item("XAAPL-USDT")


def test_add_item_custom_group_is_registered() -> None:
    _seed_instruments(make_ref())
    _daily("XAAPL-USDT", ["100", "110"])

    entry = add_item("XAAPL-USDT", " 核心持仓 ")

    assert entry is not None
    assert entry.group == "核心持仓"
    assert list_groups() == ["核心持仓"]


def test_move_item_creates_new_group_and_drops_empty_source() -> None:
    _seed_instruments(make_ref())
    _daily("XAAPL-USDT", ["100", "110"])
    add_item("XAAPL-USDT")

    moved = move_item("XAAPL-USDT", "观察")

    assert moved is not None
    assert moved.group == "观察"
    assert list_groups() == ["观察"]
    assert list_entries()[0].group == "观察"


def test_move_unknown_item_returns_none() -> None:
    assert move_item("XAAPL-USDT", "观察") is None


def test_remove_item_drops_alerts_and_empty_group() -> None:
    _seed_instruments(make_ref())
    _daily("XAAPL-USDT", ["100", "110"])
    add_item("XAAPL-USDT")
    set_alert("XAAPL-USDT", "above", Decimal("120"))

    assert remove_item("XAAPL-USDT") is True
    assert remove_item("XAAPL-USDT") is False
    assert list_entries() == []
    assert list_groups() == []
    assert clear_alert("XAAPL-USDT") is False


def test_set_alert_stores_rule_and_overwrites_in_place() -> None:
    _seed_instruments(make_ref())
    _daily("XAAPL-USDT", ["100", "110"])
    add_item("XAAPL-USDT")

    created = set_alert("XAAPL-USDT", "above", Decimal("120.5"))
    assert created is not None
    assert created.direction == "above"
    assert created.price == Decimal("120.5")
    assert created.enabled is True
    assert created.triggered_at is None

    updated = set_alert("XAAPL-USDT", "below", Decimal("99"), enabled=False)
    assert updated is not None
    assert (updated.direction, updated.price, updated.enabled) == (
        "below",
        Decimal("99"),
        False,
    )
    assert list_entries()[0].alert is not None
    assert clear_alert("XAAPL-USDT") is True
    assert list_entries()[0].alert is None


def test_set_alert_requires_watchlist_item() -> None:
    _seed_instruments(make_ref())

    assert set_alert("XAAPL-USDT", "above", Decimal("120")) is None


def test_related_instruments_ranks_by_absolute_correlation() -> None:
    _seed_instruments(
        make_ref(),
        make_swap_ref(),
        make_ref(inst_id="XMSFT-USDT", base_ccy="XMSFT"),
    )
    # XAAPL 与拟合同步上涨的标的完全正相关；XMSFT 反向且不完美。
    _daily("XAAPL-USDT", ["10", "20", "30", "40", "50"])
    _daily("AAPL-USDT-SWAP", ["20", "40", "60", "80", "100"])
    _daily("XMSFT-USDT", ["50", "40", "30", "20", "20"])

    related = related_instruments("XAAPL-USDT", 180)

    assert related is not None
    assert [item.inst_id for item in related] == ["AAPL-USDT-SWAP", "XMSFT-USDT"]
    assert related[0].correlation == Decimal("1.0000")
    assert abs(related[1].correlation) < Decimal("1")
    assert related[0].product_key == "AAPL"
    assert related[0].asset_type == "tokenized_equity"


def test_related_instruments_unknown_symbol_returns_none() -> None:
    assert related_instruments("UNKNOWN-USDT", 30) is None


def test_related_instruments_skips_candidates_without_enough_data() -> None:
    _seed_instruments(make_ref(), make_swap_ref())
    _daily("XAAPL-USDT", ["10", "20", "30", "40", "50"])
    _daily("AAPL-USDT-SWAP", ["20", "40"])

    assert related_instruments("XAAPL-USDT", 180) == []

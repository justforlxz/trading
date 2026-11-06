"""真实美股行情（AC5/AC6）：Yahoo 解析、缺失登记、基差记录与阈值告警。"""

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select

from app.adapters.equity.yahoo import YahooEquitySource
from app.market.equity import (
    compute_basis_bps,
    ensure_equity_assets,
    list_basis,
    record_basis,
    sync_equity_candles,
)
from app.market.models import DataQualityIssue, EquityAsset, EquityCandle, Instrument
from app.ports.market_data import EquityQuote
from tests.market.support import (
    FakeEquitySource,
    insert_instrument,
    load_fixture,
    make_equity_rows,
)

QUOTE_TS = datetime(2026, 11, 6, 18, 0, tzinfo=UTC)


def _yahoo_source() -> YahooEquitySource:
    fixture = load_fixture("yahoo_chart_aapl.json")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=fixture))
    return YahooEquitySource(transport=transport)


async def test_yahoo_daily_parses_recorded_chart() -> None:
    source = _yahoo_source()
    rows = await source.fetch_daily("AAPL", lookback_days=5)
    assert len(rows) >= 5
    assert all(row.interval == "1d" for row in rows)
    assert all(row.source == "yahoo" for row in rows)
    assert [row.ts for row in rows] == sorted(row.ts for row in rows)
    assert rows[-1].close == Decimal("344.17")


async def test_yahoo_quote_uses_regular_market_price() -> None:
    quote = await _yahoo_source().fetch_quote("AAPL")
    assert quote is not None
    assert quote.price == Decimal("344.17")
    assert quote.source == "yahoo"


async def test_ensure_equity_assets_maps_only_tradable_shares(session) -> None:
    await insert_instrument(session, "AAPL-USDT-SWAP")
    await insert_instrument(session, "SPY-USDT-SWAP", asset_class="etf", exchange="NYSE_ARCA")
    await insert_instrument(
        session, "OPENAI-USDT-SWAP", asset_class="private_company", exchange=None
    )

    assets = await ensure_equity_assets(session, FakeEquitySource())
    assert [asset.symbol for asset in assets] == ["AAPL", "SPY"]
    assert all(asset.source_name == "fake" for asset in assets)
    assert all(asset.mapping_status == "mapped" for asset in assets)


async def test_sync_writes_candles_for_mapped_asset(session) -> None:
    await insert_instrument(session, "AAPL-USDT-SWAP")
    rows = make_equity_rows(5)
    result = await sync_equity_candles(session, FakeEquitySource(rows))
    assert result.candles_written == 5
    assert result.missing == []

    stored = await session.scalar(select(func.count()).select_from(EquityCandle))
    assert stored == 5

    again = await sync_equity_candles(session, FakeEquitySource(rows))
    assert again.candles_written == 5
    assert await session.scalar(select(func.count()).select_from(EquityCandle)) == 5


async def test_source_failure_records_missing_source_not_fake_prices(session) -> None:
    await insert_instrument(session, "AAPL-USDT-SWAP")
    result = await sync_equity_candles(session, FakeEquitySource(unavailable=True))
    assert result.missing == ["AAPL"]
    assert await session.scalar(select(func.count()).select_from(EquityCandle)) == 0

    issue = await session.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.dataset == "market.equity_candle",
            DataQualityIssue.kind == "MISSING_SOURCE",
        )
    )
    assert issue is not None
    assert issue.detail["source"] == "fake"


def test_basis_matches_recorded_prices() -> None:
    """实测 2026-11-06：OKX last 343.28 vs Yahoo 收盘 344.17。"""

    basis = compute_basis_bps(Decimal("343.28"), Decimal("344.17"))
    assert abs(basis - Decimal("-25.86")) < Decimal("0.05")
    assert compute_basis_bps(Decimal("100"), Decimal("0")) == Decimal("0")


async def test_basis_snapshot_is_queryable(session) -> None:
    instrument = await insert_instrument(session, "AAPL-USDT-SWAP")
    quote = EquityQuote(symbol="AAPL", price=Decimal("344.17"), ts=QUOTE_TS, source="yahoo")
    stored = await record_basis(
        session, instrument=instrument, okx_price=Decimal("343.28"), quote=quote
    )
    assert stored.basis_bps == compute_basis_bps(Decimal("343.28"), Decimal("344.17"))

    rows = await list_basis(session, inst_id=instrument.inst_id)
    assert len(rows) == 1
    assert rows[0].source == "yahoo"

    issues = list(
        await session.scalars(select(DataQualityIssue).where(DataQualityIssue.kind == "OUTLIER"))
    )
    assert issues == []


async def test_basis_over_threshold_records_outlier(session) -> None:
    instrument = await insert_instrument(session, "AAPL-USDT-SWAP")
    quote = EquityQuote(symbol="AAPL", price=Decimal("344.17"), ts=QUOTE_TS, source="yahoo")
    await record_basis(
        session,
        instrument=instrument,
        okx_price=Decimal("400.00"),
        quote=quote,
        alert_bps=500,
    )
    issue = await session.scalar(select(DataQualityIssue).where(DataQualityIssue.kind == "OUTLIER"))
    assert issue is not None
    assert issue.dataset == "market.basis"
    assert issue.detail["threshold_bps"] == 500


@pytest.mark.parametrize("symbol", ["AAPL", "SPY"])
async def test_equity_asset_symbol_mapping(session, symbol: str) -> None:
    await insert_instrument(session, f"{symbol}-USDT-SWAP")
    assets = await ensure_equity_assets(session, FakeEquitySource())
    stored = await session.scalar(select(EquityAsset).where(EquityAsset.symbol == symbol))
    assert stored is not None
    assert stored.symbol in {asset.symbol for asset in assets}

    instruments = await session.scalar(select(func.count()).select_from(Instrument))
    assert instruments == 1

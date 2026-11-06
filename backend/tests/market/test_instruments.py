"""标的同步（AC2）：真实录制响应解析、幂等 upsert、分类与分页。"""

import httpx
from sqlalchemy import func, select

from app.adapters.okx.client import OkxClient
from app.adapters.okx.instruments import OkxInstrumentSource
from app.market.instruments import (
    count_instruments,
    get_instrument,
    list_instruments,
    sync_instruments,
)
from app.market.models import Instrument
from app.ports.market_data import InstrumentRow
from tests.market.support import FakeInstrumentSource, fixture_instrument_rows, load_fixture


def _mock_source() -> OkxInstrumentSource:
    fixture = load_fixture("instruments_swap.json")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"code": "0", "msg": "", "data": fixture["data"]})
    )
    return OkxInstrumentSource(OkxClient(transport=transport))


async def test_adapter_parses_recorded_snapshot() -> None:
    rows = await _mock_source().fetch_instruments()
    assert len(rows) == len(load_fixture("instruments_swap.json")["data"])

    aapl = next(row for row in rows if row.inst_id == "AAPL-USDT-SWAP")
    assert aapl.asset_class == "us_equity"
    assert aapl.exchange == "XNAS"
    assert aapl.inst_category == 3
    assert str(aapl.ct_val) == "1"

    openai = next(row for row in rows if row.inst_id == "OPENAI-USDT-SWAP")
    assert openai.asset_class == "private_company"
    assert openai.exchange is None


async def test_sync_is_idempotent_and_keeps_synced_at(session) -> None:
    rows = fixture_instrument_rows()
    source = FakeInstrumentSource(rows)

    first = await sync_instruments(session, source)
    assert first.fetched == len(rows)
    assert first.inserted == len(rows)
    assert first.updated == 0
    assert await count_instruments(session) == len(rows)

    second = await sync_instruments(session, source)
    assert second.inserted == 0
    assert second.updated == len(rows)
    assert await count_instruments(session) == len(rows)

    stored = list(await session.scalars(select(Instrument)))
    assert all(row.source_synced_at is not None for row in stored)
    assert all(row.asset_class for row in stored)
    assert {row.asset_class for row in stored} - {"unclassified"}


async def test_stock_rows_all_have_asset_class(session) -> None:
    await sync_instruments(session, FakeInstrumentSource(fixture_instrument_rows()))
    stocks = list(await session.scalars(select(Instrument).where(Instrument.inst_category == 3)))
    assert stocks
    for row in stocks:
        assert row.asset_class

    openai = await get_instrument(session, "OPENAI-USDT-SWAP")
    assert openai is not None
    assert openai.asset_class == "private_company"
    assert openai.exchange is None


async def test_list_instruments_paginates_and_filters(session) -> None:
    await sync_instruments(session, FakeInstrumentSource(fixture_instrument_rows()))

    page, cursor = await list_instruments(session, limit=5)
    assert len(page) == 5
    assert cursor is not None
    next_page, _ = await list_instruments(session, limit=5, cursor=cursor)
    assert {row.inst_id for row in page}.isdisjoint({row.inst_id for row in next_page})

    etfs, _ = await list_instruments(session, limit=50, asset_class="etf")
    assert etfs and all(row.asset_class == "etf" for row in etfs)

    searched, _ = await list_instruments(session, limit=50, query="aapl")
    assert [row.inst_id for row in searched] == ["AAPL-USDT-SWAP"]


async def test_by_asset_class_summary_matches_rows(session) -> None:
    result = await sync_instruments(session, FakeInstrumentSource(fixture_instrument_rows()))
    rows: list[InstrumentRow] = fixture_instrument_rows()
    expected: dict[str, int] = {}
    for row in rows:
        expected[row.asset_class] = expected.get(row.asset_class, 0) + 1
    assert result.by_asset_class == expected

    total = await session.scalar(select(func.count()).select_from(Instrument))
    assert total == len(rows)

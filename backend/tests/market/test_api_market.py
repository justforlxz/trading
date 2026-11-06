"""HTTP 契约（AC2/AC3/AC6/AC7/AC8）：标的、K 线、日历、覆盖率与错误信封。"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

from sqlalchemy import select

from app.api.v1 import market as market_api
from app.jobs import runs, tasks
from app.market import sync_status
from app.market.candles import upsert_candles
from app.market.equity import record_basis
from app.market.instruments import count_instruments
from app.market.models import DataQualityIssue
from app.ops.quality import record_issue
from app.ports.market_data import EquityQuote
from tests.market.support import (
    FakeInstrumentSource,
    fixture_instrument_rows,
    insert_instrument,
    make_candle_rows,
)


async def test_sync_instruments_twice_second_is_skipped(session, client, monkeypatch) -> None:
    source = FakeInstrumentSource(fixture_instrument_rows())

    async def fake_dispatch(task_name: str, **kwargs: object) -> None:
        from app.db.session import session_factory

        assert task_name == tasks.SYNC_INSTRUMENTS
        async with session_factory() as db:
            await tasks.run_sync_instruments(db, source)

    monkeypatch.setattr(market_api, "dispatch", fake_dispatch)

    first = await client.post("/api/v1/market/sync/instruments")
    assert first.status_code == 202
    body = first.json()
    assert body["status"] == "queued"
    assert body["job_key"]

    second = await client.post("/api/v1/market/sync/instruments")
    assert second.status_code == 200
    assert second.json()["status"] == "skipped"
    assert second.json()["job_key"] == body["job_key"]

    assert await count_instruments(session) == len(fixture_instrument_rows())

    listed = await client.get("/api/v1/market/instruments", params={"limit": 200})
    items = listed.json()["items"]
    assert items
    assert all(item["source_synced_at"] for item in items)
    assert all(item["asset_class"] for item in items)


async def test_unknown_instrument_returns_error_envelope(client) -> None:
    response = await client.get("/api/v1/market/instruments/NOPE-USDT-SWAP")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INSTRUMENT_NOT_FOUND"
    assert response.headers["X-Request-ID"]


async def test_candles_are_ascending_and_paginated(session, client) -> None:
    instrument = await insert_instrument(session)
    start = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
    await upsert_candles(
        session, instrument.id, make_candle_rows(start=start, count=10, confirm_last=True)
    )

    response = await client.get(
        "/api/v1/market/candles",
        params={"inst_id": instrument.inst_id, "bar": "1h", "limit": 10},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["bar"] == "1h"
    times = [datetime.fromisoformat(item["open_time"]) for item in body["items"]]
    assert times == sorted(times)
    assert len(set(times)) == 10
    for previous, current in pairwise(times):
        assert current - previous == timedelta(hours=1)
    assert [item["confirm"] for item in body["items"]][-1] is False


async def test_unsupported_bar_returns_400(client) -> None:
    response = await client.get(
        "/api/v1/market/candles", params={"inst_id": "AAPL-USDT-SWAP", "bar": "8H"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_BAR"


async def test_sessions_endpoint_returns_dst_and_half_day(client) -> None:
    response = await client.get(
        "/api/v1/market/sessions", params={"from": "2026-03-01", "to": "2026-03-20"}
    )
    assert response.status_code == 200
    items = {item["trading_date"]: item for item in response.json()["items"]}
    assert datetime.fromisoformat(items["2026-03-06"]["regular_start"]) == datetime(
        2026, 3, 6, 14, 30, tzinfo=UTC
    )
    assert datetime.fromisoformat(items["2026-03-09"]["regular_start"]) == datetime(
        2026, 3, 9, 13, 30, tzinfo=UTC
    )

    november = await client.get(
        "/api/v1/market/sessions", params={"from": "2026-11-26", "to": "2026-11-27"}
    )
    days = {item["trading_date"]: item for item in november.json()["items"]}
    assert days["2026-11-26"]["is_session"] is False
    assert days["2026-11-27"]["is_half_day"] is True


async def test_coverage_endpoint_reports_gap(session, client) -> None:
    instrument = await insert_instrument(session)
    start = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
    rows = make_candle_rows(start=start, count=24)
    await upsert_candles(session, instrument.id, rows[:20])

    response = await client.get(
        "/api/v1/market/coverage",
        params={
            "inst_id": instrument.inst_id,
            "bar": "1h",
            "start": start.isoformat(),
            "end": (start + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {"expected": 24, "actual": 20, "missing": 4, "ratio": 20 / 24}
    assert body["days"][0]["gaps"][0]["window_start"] == (start + timedelta(hours=20)).isoformat()


async def test_quality_issues_endpoint_lists_recorded_issues(session, client) -> None:
    await record_issue(
        session,
        dataset="market.candle",
        scope_id="AAPL-USDT-SWAP:1h",
        kind="GAP",
        window_start=datetime(2026, 11, 6, 1, 0, tzinfo=UTC),
    )
    await session.commit()

    response = await client.get("/api/v1/market/quality-issues")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "GAP"
    assert await session.scalar(select(DataQualityIssue.id)) is not None


async def test_basis_endpoint_returns_snapshot(session, client) -> None:
    instrument = await insert_instrument(session)
    quote = EquityQuote(
        symbol="AAPL",
        price=Decimal("344.17"),
        ts=datetime(2026, 11, 6, 18, 0, tzinfo=UTC),
        source="yahoo",
    )
    await record_basis(session, instrument=instrument, okx_price=Decimal("343.28"), quote=quote)

    response = await client.get("/api/v1/market/basis", params={"inst_id": instrument.inst_id})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["source"] == "yahoo"
    assert items[0]["equity_price"] == "344.1700000000"


async def test_failed_run_can_be_retried_with_same_payload(session, client, monkeypatch) -> None:
    calls: list[object] = []

    async def fake_dispatch(task_name: str, **kwargs: object) -> None:
        calls.append(kwargs.get("run_id"))

    monkeypatch.setattr(market_api, "dispatch", fake_dispatch)

    first = await client.post("/api/v1/market/sync/instruments")
    run_id = first.json()["job_id"]
    await runs.finish_run(session, run_id, "failed", error="boom")

    second = await client.post("/api/v1/market/sync/instruments")
    assert second.status_code == 202
    assert second.json()["job_id"] == run_id
    assert len(calls) == 2


async def test_partial_run_can_be_retried_with_same_payload(session, client, monkeypatch) -> None:
    calls: list[object] = []

    async def fake_dispatch(task_name: str, **kwargs: object) -> None:
        calls.append(kwargs.get("run_id"))

    monkeypatch.setattr(market_api, "dispatch", fake_dispatch)

    first = await client.post("/api/v1/market/sync/instruments")
    run_id = first.json()["job_id"]
    await runs.finish_run(session, run_id, "partial", result={"status": "partial"})

    second = await client.post("/api/v1/market/sync/instruments")
    assert second.status_code == 202
    assert len(calls) == 2


async def test_sync_status_reports_ledger_and_stale(session, client) -> None:
    now = datetime.now(tz=UTC)
    await sync_status.record_sync(
        session,
        source=sync_status.SOURCE_OKX,
        dataset=sync_status.DATASET_INSTRUMENTS,
        scope="SWAP",
        window_start=now,
        window_end=now,
        status="ok",
        rows_written=543,
    )
    await session.commit()

    body = (await client.get("/api/v1/market/sync-status")).json()
    items = {(item["source"], item["dataset"], item["scope"]): item for item in body["items"]}
    item = items[("okx", "market.instrument", "SWAP")]
    assert item["status"] == "ok"
    assert item["last_success_at"] is not None
    assert item["stale"] is False
    assert body["stale"] == 0


async def test_quality_issues_supports_status_filter(session, client) -> None:
    await record_issue(
        session,
        dataset="market.candle",
        scope_id="AAPL-USDT-SWAP:1h",
        kind="GAP",
        window_start=datetime(2026, 11, 6, 1, 0, tzinfo=UTC),
    )
    await session.commit()

    open_items = (await client.get("/api/v1/market/quality-issues?status=open")).json()["items"]
    resolved_items = (await client.get("/api/v1/market/quality-issues?status=resolved")).json()[
        "items"
    ]
    assert len(open_items) == 1
    assert resolved_items == []

    bad = await client.get("/api/v1/market/quality-issues?status=bogus")
    assert bad.status_code == 400

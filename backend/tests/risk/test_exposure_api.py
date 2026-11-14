"""风险与敞口 HTTP 契约：真实同步路径、手算结果与错误码。"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core import Bar, Timeframe
from app.db import session_scope
from app.exchange.okx.instruments import parse_instruments
from app.instrument import Instrument, sync_instruments
from app.main import create_app
from app.market import upsert_candles
from tests.exchange.conftest import SPOT_INST_ID, SPOT_INSTRUMENT, SWAP_INST_ID, SWAP_INSTRUMENT
from tests.fakes.okx.server import FakeOkxServer

D = Decimal
TWELVE_PLACES = D("0.000000000001")
BTC_SWAP_INST_ID = "BTC-USDT-SWAP"
BTC_SWAP_INSTRUMENT = {
    "instId": BTC_SWAP_INST_ID,
    "instType": "SWAP",
    "baseCcy": "",
    "quoteCcy": "",
    "ctValCcy": "BTC",
    "settleCcy": "USDT",
    "ctVal": "0.01",
    "ctMult": "1",
    "ctType": "linear",
    "lever": "20",
    "state": "live",
    "instCategory": "1",
    "tickSz": "0.1",
    "lotSz": "0.01",
    "minSz": "0.01",
    "listTime": "1760000000000",
}


def _q12(value: Decimal) -> Decimal:
    return value.quantize(TWELVE_PLACES)


@pytest.fixture()
def api(fake_okx_server: FakeOkxServer, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    credentials = fake_okx_server.store.book.credentials
    monkeypatch.setenv("OKX_API_KEY", credentials.api_key)
    monkeypatch.setenv("OKX_SECRET_KEY", credentials.secret)
    monkeypatch.setenv("OKX_PASSPHRASE", credentials.passphrase)
    monkeypatch.setenv("OKX_DEMO", "1")
    monkeypatch.setenv("OKX_REST_BASE_URL", fake_okx_server.base_url)
    monkeypatch.setenv("OKX_HTTP_MAX_RETRIES", "0")
    monkeypatch.setenv("OKX_RATE_LIMIT_CAPACITY", "1000")
    monkeypatch.setenv("OKX_RATE_LIMIT_REFILL_PER_SECOND", "1000")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        sync_instruments(parse_instruments([SPOT_INSTRUMENT, SWAP_INSTRUMENT]))
        _seed_atr(SWAP_INST_ID, price="231.42", atr="2", count=15)
        with session_scope() as session:
            session.get(Instrument, SWAP_INST_ID).sector = "semiconductor"
            session.get(Instrument, SPOT_INST_ID).sector = "semiconductor"
        yield client
    get_settings.cache_clear()


def _seed_atr(inst_id: str, *, price: str, atr: str, count: int, source: str = "okx_swap") -> None:
    """构造一个恒定真实波幅的日线序列，ATR(14) 恰好等于给定值。"""

    close = D(price)
    half = D(atr) / D(2)
    end = (datetime.now(UTC) - timedelta(days=1)).replace(
        hour=16, minute=0, second=0, microsecond=0
    )
    opens = [end - timedelta(days=count - 1 - index) for index in range(count)]
    upsert_candles(
        [
            Bar(
                inst_id=inst_id,
                timeframe=Timeframe.parse("1d"),
                open_time=open_time,
                open=close,
                high=close + half,
                low=close - half,
                close=close,
                volume=D("10"),
                confirm=True,
                source=source,
            )
            for open_time in opens
        ]
    )


def _sync_exchange_position(fake_okx_server: FakeOkxServer, api: TestClient) -> None:
    book = fake_okx_server.store.book
    book.set_account(
        equity="1248.60",
        available_equity="682.30",
        used_margin="566.30",
        unrealized_pnl="31.84",
        margin_ratio="0.4536",
    )
    book.set_balance("USDT", available="682.30")
    book.set_position(
        SWAP_INST_ID,
        qty="8",
        pos_side="long",
        avg_price="226.80",
        pos_id="123456",
        mark_px="231.42",
        upl="36.96",
        upl_ratio="0.0204",
        lever="3",
        liq_px="151.20",
        margin="604.80",
    )
    synced = api.post("/api/account/sync")
    assert synced.status_code == 200, synced.text


def test_exchange_position_exposure_matches_hand_calculation(
    api: TestClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    _sync_exchange_position(fake_okx_server, api)

    before = api.get("/api/risk/exposure")
    assert before.status_code == 200, before.text
    body = before.json()
    assert body["status"] == "ok"
    assert body["summary"]["currency"] == "USDT"
    assert D(body["summary"]["long_notional"]) == D("8") * D("231.42")
    assert D(body["summary"]["short_notional"]) == D("0")
    assert D(body["summary"]["net_notional"]) == D("1851.36")
    assert D(body["summary"]["gross_notional"]) == D("1851.36")
    assert D(body["summary"]["margin_usage_pct"]) == _q12(D("566.30") / D("1248.60") * D("100"))
    assert body["summary"]["margin_usage_basis"] == "margin_ratio"
    assert body["summary"]["risk_level"] == "medium"

    position = body["positions"][0]
    assert position["position_ref"] == "exchange:okx-main:123456"
    assert position["source"] == "exchange"
    assert position["display_symbol"] == "AAPL-USDT"
    assert position["side"] == "long"
    assert D(position["notional"]) == D("1851.36")
    assert D(position["weight_pct"]) == D("100")
    assert position["stop_px"] is None
    assert position["stop_distance_pct"] is None
    assert position["atr_distance"] is None
    assert position["flags"] == ["stop_missing", "single_instrument_weight"]
    assert body["sectors"] == [
        {"sector": "semiconductor", "notional": "1851.36", "weight_pct": "100"}
    ]
    assert [rule["rule_id"] for rule in body["rules"]] == [
        "stop_missing",
        "single_instrument_weight",
    ]

    saved = api.put(
        "/api/positions/exchange:okx-main:123456/risk-config",
        json={"stop_px": "230", "risk_budget": "50", "warning_threshold_pct": "1.5"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["position_ref"] == "exchange:okx-main:123456"
    assert D(saved.json()["stop_px"]) == D("230")
    assert D(saved.json()["risk_budget"]) == D("50")
    assert saved.json()["source"] == "local"

    updated = api.put(
        "/api/positions/exchange:okx-main:123456/risk-config",
        json={"risk_budget": "75"},
    )
    assert updated.status_code == 200, updated.text
    assert D(updated.json()["stop_px"]) == D("230")
    assert D(updated.json()["risk_budget"]) == D("75")

    after = api.get("/api/risk/exposure").json()
    position = after["positions"][0]
    expected_stop_pct = (D("231.42") - D("230")) / D("231.42") * D("100")
    expected_atr_distance = (D("231.42") - D("230")) / D("2")
    assert D(position["stop_px"]) == D("230")
    assert D(position["stop_distance_pct"]) == _q12(expected_stop_pct)
    assert D(position["atr_distance"]) == expected_atr_distance
    assert position["flags"] == ["stop_distance", "single_instrument_weight"]
    rule = next(item for item in after["rules"] if item["rule_id"] == "stop_distance")
    assert D(rule["value"]) == expected_atr_distance
    assert D(rule["threshold"]) == D("1")
    assert rule["level"] == "warning"
    assert after["summary"]["risk_level"] == "medium"


def test_manual_position_is_included_with_source_and_local_stop(api: TestClient) -> None:
    created = api.post(
        "/api/manual-positions",
        json={
            "inst_id": SWAP_INST_ID,
            "side": "long",
            "quantity": "2",
            "avg_cost": "200",
            "stop_px": "225",
            "leverage": "2",
            "idempotency_key": "manual-exposure-1",
        },
    )
    assert created.status_code == 201, created.text
    position_id = created.json()["id"]

    body = api.get("/api/risk/exposure").json()
    item = body["positions"][0]
    assert item["position_ref"] == f"manual:{position_id}"
    assert item["source"] == "manual"
    assert item["display_symbol"] == "AAPL-USDT"
    assert D(item["notional"]) == D("2") * D("231.42")
    assert D(item["stop_px"]) == D("225")
    assert D(item["stop_distance_pct"]) == _q12((D("231.42") - D("225")) / D("231.42") * D("100"))
    assert D(item["atr_distance"]) == (D("231.42") - D("225")) / D("2")
    assert body["summary"]["margin_usage_pct"] is None
    assert body["summary"]["margin_usage_basis"] is None


def test_manual_quantity_and_proxy_only_bars_do_not_leak_into_margin(api: TestClient) -> None:
    sync_instruments(parse_instruments([BTC_SWAP_INSTRUMENT]))
    _seed_atr(BTC_SWAP_INST_ID, price="100", atr="2", count=15, source="us_equity_proxy")

    created = api.post(
        "/api/manual-positions",
        json={
            "inst_id": BTC_SWAP_INST_ID,
            "side": "long",
            "quantity": "2",
            "avg_cost": "90",
            "stop_px": "95",
            "leverage": "2",
            "idempotency_key": "manual-exposure-contract-multiplier",
        },
    )
    assert created.status_code == 201, created.text

    body = api.get("/api/risk/exposure").json()
    item = body["positions"][0]
    assert D(item["notional"]) == D("2") * D("100")
    assert D(item["stop_distance_pct"]) == _q12((D("100") - D("95")) / D("100") * D("100"))
    assert item["atr_distance"] is None
    assert item["flags"] == ["atr_unavailable", "single_instrument_weight"]
    assert D(body["summary"]["gross_notional"]) == D("200")


def test_unknown_position_ref_is_404_and_invalid_price_is_422(api: TestClient) -> None:
    missing = api.put(
        "/api/positions/manual:does-not-exist/risk-config",
        json={"stop_px": "100"},
    )
    assert missing.status_code == 404, missing.text

    created = api.post(
        "/api/manual-positions",
        json={
            "inst_id": SWAP_INST_ID,
            "side": "long",
            "quantity": "1",
            "avg_cost": "200",
            "idempotency_key": "manual-invalid-price",
        },
    )
    assert created.status_code == 201, created.text
    ref = f"manual:{created.json()['id']}"

    negative = api.put(f"/api/positions/{ref}/risk-config", json={"stop_px": "-1"})
    zero = api.put(f"/api/positions/{ref}/risk-config", json={"stop_px": "0"})
    malformed = api.put(f"/api/positions/{ref}/risk-config", json={"stop_px": "abc"})

    assert negative.status_code == 422, negative.text
    assert zero.status_code == 422, zero.text
    assert malformed.status_code == 422, malformed.text

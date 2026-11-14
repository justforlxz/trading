"""持仓 HTTP 契约：OKX 只读同步、手动持仓流水的数值与幂等。"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core import AccountSnapshot, ExchangePosition, ReplayClock
from app.db import session_scope
from app.exchange.okx.instruments import parse_instruments
from app.instrument import sync_instruments
from app.main import create_app
from app.positions import account_summary, exchange_positions, record_exchange_snapshot
from app.positions.model import AccountSnapshotRow, ManualPositionRow
from tests.api.conftest import seed_daily
from tests.exchange.conftest import SPOT_INSTRUMENT, SWAP_INST_ID, SWAP_INSTRUMENT
from tests.factories.instruments import make_ref
from tests.fakes.okx.server import FakeOkxServer


@pytest.fixture()
def api(fake_okx_server: FakeOkxServer, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """指向假 OKX 的应用；标的走真实同步路径，日线走真实 upsert 路径。"""

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
        seed_daily(SWAP_INST_ID, ["50", "55", "60.5"])
        yield client
    get_settings.cache_clear()


@pytest.fixture()
def bare_client(
    fake_okx_server: FakeOkxServer, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """没有配置任何 OKX 凭据的应用。"""

    for name in ("OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE"):
        monkeypatch.setenv(name, "")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


def test_sync_then_summary_and_exchange_positions_share_captured_at(
    api: TestClient,
    fake_okx_server: FakeOkxServer,
) -> None:
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
    body = synced.json()
    assert body["status"] == "ok"
    assert body["positions_synced"] == 1
    assert Decimal(body["equity"]) == Decimal("1248.60")
    assert Decimal(body["available_equity"]) == Decimal("682.30")
    assert Decimal(body["used_margin"]) == Decimal("566.30")
    assert float(Decimal(body["margin_usage_pct"])) == pytest.approx(
        float(Decimal("566.30") / Decimal("1248.60") * 100)
    )
    assert body["day_pnl"] is None
    assert body["day_pnl_basis"] == "equity_only"

    summary = api.get("/api/account/summary")
    positions = api.get("/api/positions/exchange")

    assert summary.status_code == 200, summary.text
    assert positions.status_code == 200, positions.text
    assert summary.json()["captured_at"] == body["captured_at"]
    assert positions.json()["as_of"] == body["captured_at"]
    item = positions.json()["items"][0]
    assert item["pos_id"] == "123456"
    assert item["inst_id"] == SWAP_INST_ID
    assert item["display_symbol"] == "AAPL-USDT"
    assert item["pos_side"] == "long"
    assert Decimal(item["size"]) == Decimal("8")
    assert Decimal(item["avg_px"]) == Decimal("226.80")
    assert Decimal(item["mark_px"]) == Decimal("231.42")
    assert Decimal(item["upl"]) == Decimal("36.96")
    assert Decimal(item["lever"]) == Decimal("3")
    assert item["mgn_mode"] == "cross"
    assert Decimal(item["liq_px"]) == Decimal("151.20")
    assert Decimal(item["margin"]) == Decimal("604.80")

    credentials = book.credentials
    assert credentials.secret not in synced.text
    assert credentials.passphrase not in synced.text
    assert all(
        path not in {"/api/v5/trade/order", "/api/v5/trade/cancel-order"}
        for _method, path, _query, _body in book.requests
    )


def test_upstream_failure_keeps_the_previous_snapshot(
    api: TestClient,
    fake_okx_server: FakeOkxServer,
) -> None:
    book = fake_okx_server.store.book
    book.set_account(equity="1000", available_equity="1000")
    assert api.post("/api/account/sync").status_code == 200
    before = api.get("/api/account/summary").json()

    fake_okx_server.scenarios.activate("upstream_error")
    failed = api.post("/api/account/sync")
    after = api.get("/api/account/summary").json()

    assert failed.status_code == 502, failed.text
    assert after["captured_at"] == before["captured_at"]
    assert after["equity"] == before["equity"]


def test_credentials_removed_marks_the_existing_snapshot_unconfigured(
    api: TestClient,
    fake_okx_server: FakeOkxServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧快照保留，但凭据撤销后状态必须降级为 unconfigured。"""

    book = fake_okx_server.store.book
    book.set_account(equity="1248.60", available_equity="682.30")
    book.set_position(
        SWAP_INST_ID,
        qty="8",
        pos_side="long",
        avg_price="226.80",
        pos_id="123456",
    )
    synced = api.post("/api/account/sync")
    assert synced.status_code == 200, synced.text
    captured_at = synced.json()["captured_at"]

    for name in ("OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE"):
        monkeypatch.setenv(name, "")
    get_settings.cache_clear()

    summary = api.get("/api/account/summary")
    positions = api.get("/api/positions/exchange")

    assert summary.status_code == 200, summary.text
    assert summary.json()["status"] == "unconfigured"
    assert summary.json()["captured_at"] == captured_at
    assert Decimal(summary.json()["equity"]) == Decimal("1248.60")
    assert positions.status_code == 200, positions.text
    assert positions.json()["status"] == "unconfigured"
    assert positions.json()["as_of"] == captured_at
    assert len(positions.json()["items"]) == 1


def test_unconfigured_returns_unconfigured_without_fake_numbers(bare_client: TestClient) -> None:
    summary = bare_client.get("/api/account/summary")
    positions = bare_client.get("/api/positions/exchange")
    synced = bare_client.post("/api/account/sync")

    assert summary.status_code == 200, summary.text
    assert summary.json()["status"] == "unconfigured"
    assert summary.json()["equity"] is None
    assert summary.json()["captured_at"] is None
    assert positions.status_code == 200, positions.text
    assert positions.json()["status"] == "unconfigured"
    assert positions.json()["as_of"] is None
    assert positions.json()["items"] == []
    assert synced.status_code == 200, synced.text
    assert synced.json()["status"] == "unconfigured"
    assert synced.json()["positions_synced"] == 0


def test_manual_position_flow_matches_hand_calculation(api: TestClient) -> None:
    created = api.post(
        "/api/manual-positions",
        json={
            "inst_id": SWAP_INST_ID,
            "side": "long",
            "quantity": "10",
            "avg_cost": "100",
            "stop_px": "90",
            "leverage": "3",
            "note": "手动记账",
            "idempotency_key": "create-1",
        },
    )

    assert created.status_code == 201, created.text
    position = created.json()
    position_id = position["id"]
    assert position["status"] == "open"
    assert Decimal(position["quantity"]) == Decimal("10")
    assert Decimal(position["avg_cost"]) == Decimal("100")
    assert Decimal(position["price"]) == Decimal("60.5")
    assert position["price_status"] == "ok"
    assert position["price_source"] == "okx"
    assert Decimal(position["market_value"]) == Decimal("605.0")
    assert Decimal(position["unrealized_pnl"]) == Decimal("-395.0")

    duplicate_create = api.post(
        "/api/manual-positions",
        json={
            "inst_id": SWAP_INST_ID,
            "side": "long",
            "quantity": "10",
            "avg_cost": "100",
            "idempotency_key": "create-1",
        },
    )
    assert duplicate_create.status_code == 201
    assert duplicate_create.json()["id"] == position_id
    trades = api.get(f"/api/manual-positions/{position_id}/trades")
    assert trades.status_code == 200
    assert len(trades.json()["items"]) == 1

    opened_at = datetime.fromisoformat(position["created_at"].replace("Z", "+00:00"))
    added = _post_trade(
        api,
        position_id,
        key="trade-1",
        action="add",
        quantity="5",
        price="110",
        fee="1",
        occurred_at=opened_at + timedelta(minutes=1),
    )
    assert added.status_code == 201, added.text
    assert Decimal(added.json()["position_quantity_after"]) == Decimal("15")
    assert Decimal(added.json()["position_avg_cost_after"]) == Decimal("103.4")
    assert added.json()["realized_pnl"] is None

    reduced = _post_trade(
        api,
        position_id,
        key="trade-2",
        action="reduce",
        quantity="5",
        price="120",
        fee="0.5",
        occurred_at=opened_at + timedelta(minutes=2),
    )
    assert reduced.status_code == 201, reduced.text
    assert Decimal(reduced.json()["position_quantity_after"]) == Decimal("10")
    assert Decimal(reduced.json()["position_avg_cost_after"]) == Decimal("103.4")
    assert Decimal(reduced.json()["realized_pnl"]) == Decimal("82.5")

    duplicate_trade = _post_trade(
        api,
        position_id,
        key="trade-2",
        action="reduce",
        quantity="5",
        price="120",
        fee="0.5",
        occurred_at=opened_at + timedelta(minutes=3),
    )
    assert duplicate_trade.status_code == 201
    assert duplicate_trade.json()["id"] == reduced.json()["id"]

    ledger = api.get(f"/api/manual-positions/{position_id}/trades").json()["items"]
    assert len(ledger) == 3
    assert [row["action"] for row in ledger] == ["reduce", "add", "open"]
    assert Decimal(ledger[2]["position_quantity_after"]) == Decimal("10")

    oversell = _post_trade(
        api,
        position_id,
        key="trade-3",
        action="reduce",
        quantity="11",
        price="120",
        occurred_at=opened_at + timedelta(minutes=4),
    )
    assert oversell.status_code == 422, oversell.text

    bad_close = _post_trade(
        api,
        position_id,
        key="trade-4",
        action="close",
        quantity="9",
        price="120",
        occurred_at=opened_at + timedelta(minutes=5),
    )
    assert bad_close.status_code == 422, bad_close.text

    forbidden_patch = api.patch(
        f"/api/manual-positions/{position_id}",
        json={"quantity": "99"},
    )
    assert forbidden_patch.status_code == 422

    delete_with_trades = api.delete(f"/api/manual-positions/{position_id}")
    assert delete_with_trades.status_code == 409, delete_with_trades.text


def test_concurrent_duplicate_idempotency_key_returns_the_original_position(
    api: TestClient,
) -> None:
    """并发重复创建：全部返回同一条原记录，不因唯一约束冲突报 500。"""

    payload = {
        "inst_id": SWAP_INST_ID,
        "side": "long",
        "quantity": "1",
        "avg_cost": "100",
        "idempotency_key": "same-key-concurrent",
    }
    workers = 6
    barrier = threading.Barrier(workers)

    def create() -> object:
        barrier.wait()
        return api.post("/api/manual-positions", json=payload)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        responses = [future.result() for future in [pool.submit(create) for _ in range(workers)]]

    assert all(response.status_code == 201 for response in responses), [
        response.text for response in responses
    ]
    position_ids = {response.json()["id"] for response in responses}
    assert len(position_ids) == 1

    position_id = position_ids.pop()
    ledger = api.get(f"/api/manual-positions/{position_id}/trades")
    assert ledger.status_code == 200, ledger.text
    assert len(ledger.json()["items"]) == 1


def test_short_manual_position_realizes_pnl_with_the_short_direction(api: TestClient) -> None:
    """空头 10 @ 100：价格 60.5 时浮盈 395；90 减仓 5 后已实现 50，与浮盈同向。"""

    created = api.post(
        "/api/manual-positions",
        json={
            "inst_id": SWAP_INST_ID,
            "side": "short",
            "quantity": "10",
            "avg_cost": "100",
            "idempotency_key": "short-create-1",
        },
    )

    assert created.status_code == 201, created.text
    position = created.json()
    position_id = position["id"]
    assert position["side"] == "short"
    assert Decimal(position["unrealized_pnl"]) == Decimal("395.0")

    opened_at = datetime.fromisoformat(position["created_at"].replace("Z", "+00:00"))
    reduced = _post_trade(
        api,
        position_id,
        key="short-trade-1",
        action="reduce",
        quantity="5",
        price="90",
        fee="0.5",
        occurred_at=opened_at + timedelta(minutes=1),
    )

    assert reduced.status_code == 201, reduced.text
    assert Decimal(reduced.json()["position_quantity_after"]) == Decimal("5")
    assert Decimal(reduced.json()["realized_pnl"]) == Decimal("49.5")

    closed = _post_trade(
        api,
        position_id,
        key="short-trade-2",
        action="close",
        quantity="5",
        price="95",
        occurred_at=opened_at + timedelta(minutes=2),
    )

    assert closed.status_code == 201, closed.text
    assert closed.json()["position_status_after"] == "closed"
    assert Decimal(closed.json()["realized_pnl"]) == Decimal("25")

    view = next(
        row for row in api.get("/api/manual-positions").json()["items"] if row["id"] == position_id
    )
    assert view["status"] == "closed"
    assert Decimal(view["unrealized_pnl"]) == Decimal("0")


def test_manual_position_without_market_data_is_unavailable(api: TestClient) -> None:
    sync_instruments([make_ref(inst_id="XETH-USDT", base_ccy="XETH")])

    created = api.post(
        "/api/manual-positions",
        json={
            "inst_id": "XETH-USDT",
            "side": "long",
            "quantity": "1",
            "avg_cost": "100",
            "idempotency_key": "no-price",
        },
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["price"] is None
    assert body["price_status"] == "unavailable"
    assert body["price_source"] is None
    assert body["market_value"] is None
    assert body["unrealized_pnl"] is None


def test_delete_only_works_without_trades(api: TestClient) -> None:
    orphan_id = str(uuid4())
    with session_scope() as session:
        session.add(
            ManualPositionRow(
                id=orphan_id,
                inst_id=SWAP_INST_ID,
                side="long",
                quantity=Decimal("0"),
                avg_cost=Decimal("0"),
                stop_px=None,
                leverage=None,
                status="closed",
                note=None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )

    deleted = api.delete(f"/api/manual-positions/{orphan_id}")
    assert deleted.status_code == 204, deleted.text


def test_day_pnl_requires_a_beijing_midnight_baseline(client: TestClient) -> None:
    baseline = datetime(2026, 11, 12, 16, 0, tzinfo=UTC)  # 北京时间 00:00
    current = datetime(2026, 11, 13, 2, 0, tzinfo=UTC)
    with session_scope() as session:
        session.add(_snapshot("baseline", "1000", baseline))
        session.add(_snapshot("current", "1120", current))

    view = account_summary(clock=ReplayClock(current))

    assert view.day_pnl == Decimal("120")


def test_day_pnl_is_null_without_a_baseline(client: TestClient) -> None:
    current = datetime(2026, 11, 13, 2, 0, tzinfo=UTC)
    with session_scope() as session:
        session.add(_snapshot("current", "1120", current))

    view = account_summary(clock=ReplayClock(current))

    assert view.day_pnl is None


def _post_trade(
    client: TestClient,
    position_id: str,
    *,
    key: str,
    action: str,
    quantity: str,
    price: str,
    occurred_at: datetime,
    fee: str = "0",
) -> object:
    return client.post(
        f"/api/manual-positions/{position_id}/trades",
        json={
            "action": action,
            "quantity": quantity,
            "price": price,
            "fee": fee,
            "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
            "note": None,
            "idempotency_key": key,
        },
    )


def _snapshot(marker: str, equity: str, captured_at: datetime) -> AccountSnapshotRow:
    return AccountSnapshotRow(
        account_id="okx-main",
        currency="USDT",
        equity=Decimal(equity),
        available_equity=Decimal(equity),
        cash_balance=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        used_margin=Decimal("0"),
        available_margin=Decimal(equity),
        margin_ratio=Decimal("0"),
        captured_at=captured_at,
        source="okx_rest",
        raw_payload_ref=marker,
    )


def test_position_batch_can_be_replaced_and_shrunk_at_one_captured_at(
    client: TestClient,
) -> None:
    sync_instruments(parse_instruments([SWAP_INSTRUMENT]))
    captured_at = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
    account = AccountSnapshot(
        currency="USDT",
        equity=Decimal("100"),
        available_equity=Decimal("80"),
        cash_balance=Decimal("50"),
        unrealized_pnl=Decimal("0"),
        used_margin=Decimal("20"),
        available_margin=Decimal("80"),
        margin_ratio=Decimal("0.2"),
    )
    first = _exchange_position("1", "2", mark_px="101")
    second = _exchange_position("2", "3", mark_px="102")

    record_exchange_snapshot(
        captured_at=captured_at,
        source="okx_ws",
        snapshot=account,
        positions=[first, second],
    )
    view = exchange_positions()
    assert view.as_of == captured_at
    assert {item.pos_id for item in view.items} == {"1", "2"}

    updated = _exchange_position("1", "5", mark_px="103")
    record_exchange_snapshot(
        captured_at=captured_at,
        source="okx_ws",
        positions=[updated, second],
    )
    view = exchange_positions()
    assert {item.pos_id: item.size for item in view.items} == {
        "1": Decimal("5"),
        "2": Decimal("3"),
    }

    record_exchange_snapshot(
        captured_at=captured_at,
        source="okx_ws",
        positions=[updated],
    )
    view = exchange_positions()
    assert [item.pos_id for item in view.items] == ["1"]


def _exchange_position(pos_id: str, size: str, *, mark_px: str) -> ExchangePosition:
    return ExchangePosition(
        pos_id=pos_id,
        inst_id=SWAP_INST_ID,
        pos_side="long",
        size=Decimal(size),
        avg_px=Decimal("100"),
        mark_px=Decimal(mark_px),
        upl=None,
        upl_ratio=None,
        lever=None,
        mgn_mode=None,
        liq_px=None,
        margin=None,
    )

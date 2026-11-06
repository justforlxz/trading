"""目标股票 CRUD 的 HTTP 契约（AC2）。"""

from sqlalchemy import func, select

from app.research.models import TargetSymbol
from tests.research.support import seed_okx_series, wave


async def _create(client, **payload):
    return await client.post("/api/v1/targets", json=payload)


async def test_create_returns_201(client):
    response = await _create(
        client, symbol="AAPL", exchange="XNAS", display_name="Apple", note="核心目标"
    )

    assert response.status_code == 201
    body = response.json()
    assert body["symbol"] == "AAPL"
    assert body["exchange"] == "XNAS"
    assert body["display_name"] == "Apple"
    assert body["note"] == "核心目标"
    assert body["enabled"] is True
    assert body["instrument_id"] is None
    assert body["created_at"]


async def test_duplicate_create_returns_existing_record(client, session):
    first = await _create(client, symbol="AAPL", exchange="XNAS")
    second = await _create(client, symbol="AAPL", exchange="XNAS", display_name="重复")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    # 重复插入不改动已有记录
    assert second.json()["display_name"] is None

    count = await session.scalar(select(func.count()).select_from(TargetSymbol))
    assert count == 1


async def test_same_symbol_on_another_exchange_is_a_new_record(client, session):
    await _create(client, symbol="AAPL", exchange="XNAS")
    response = await _create(client, symbol="AAPL", exchange="NYSE_ARCA")

    assert response.status_code == 201
    count = await session.scalar(select(func.count()).select_from(TargetSymbol))
    assert count == 2


async def test_create_links_instrument_when_listed(client, session):
    ids = await seed_okx_series(session, {"AAPL-USDT-SWAP": wave(10)})

    body = (await _create(client, symbol="AAPL", exchange="XNAS")).json()

    assert body["instrument_id"] == ids["AAPL-USDT-SWAP"]


async def test_list_excludes_soft_deleted_by_default(client):
    kept = (await _create(client, symbol="AAPL", exchange="XNAS")).json()
    dropped = (await _create(client, symbol="MSFT", exchange="XNAS")).json()

    deleted = await client.delete(f"/api/v1/targets/{dropped['id']}")
    assert deleted.status_code == 200

    default_list = (await client.get("/api/v1/targets")).json()
    assert [item["id"] for item in default_list["items"]] == [kept["id"]]

    disabled_list = (await client.get("/api/v1/targets", params={"enabled": "false"})).json()
    assert [item["id"] for item in disabled_list["items"]] == [dropped["id"]]


async def test_delete_is_soft_and_keeps_row(client, session):
    created = (await _create(client, symbol="AAPL", exchange="XNAS")).json()

    response = await client.delete(f"/api/v1/targets/{created['id']}")

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    row = await session.scalar(select(TargetSymbol).where(TargetSymbol.id == created["id"]))
    assert row is not None
    assert row.enabled is False


async def test_exchange_is_required_and_validated(client):
    missing = await client.post("/api/v1/targets", json={"symbol": "AAPL"})
    assert missing.status_code == 422

    unknown = await _create(client, symbol="AAPL", exchange="NYSE")
    assert unknown.status_code == 422

    blank = await _create(client, symbol="  ", exchange="XNAS")
    assert blank.status_code == 422


async def test_patch_updates_display_name_and_keeps_other_fields(client):
    created = (await _create(client, symbol="AAPL", exchange="XNAS", note="旧备注")).json()

    response = await client.patch(f"/api/v1/targets/{created['id']}", json={"display_name": "苹果"})

    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "苹果"
    assert body["note"] == "旧备注"


async def test_unknown_target_returns_404(client):
    response = await client.get("/api/v1/targets/987654")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TARGET_NOT_FOUND"

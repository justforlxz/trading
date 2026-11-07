"""paper 模式：模式端点、零真实调用、部分成交推进。"""

from decimal import Decimal

from sqlalchemy import select

from app.execution.models import Fill, Order
from tests.execution.conftest import seed_execution_strategy


def _payload(strategy_id: int) -> dict:
    return {
        "strategy_id": strategy_id,
        "inst_id": "BTC-USDT-SWAP",
        "side": "buy",
        "position_side": "long",
        "quantity": "1",
        "order_type": "market",
    }


async def test_mode_endpoint_reports_paper(client) -> None:
    response = await client.get("/api/v1/execution/mode")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "paper"
    assert body["real_trading_enabled"] is False
    assert body["credentials_configured"] is False
    assert body["reason"] == "real_trading_disabled"


async def test_paper_order_never_builds_real_client(client, session, monkeypatch) -> None:
    seeded = await seed_execution_strategy(session)

    def _boom(*args, **kwargs):  # pragma: no cover - 命中即失败
        raise AssertionError("paper 下单不得构造真实交易所客户端")

    monkeypatch.setattr("app.execution.service.OkxPrivateClient", _boom)

    response = await client.post(
        "/api/v1/execution/paper/orders", json=_payload(seeded.strategy_id)
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["mode"] == "paper"
    assert body["state"] == "partial"
    assert body["filled_quantity"] == "0.5"

    synced = await client.post(f"/api/v1/execution/orders/{body['id']}/sync")
    assert synced.status_code == 200
    assert synced.json()["state"] == "filled"
    assert synced.json()["filled_quantity"] == "1"


async def test_paper_order_records_fills_and_position(client, session) -> None:
    seeded = await seed_execution_strategy(session)
    response = await client.post(
        "/api/v1/execution/paper/orders", json=_payload(seeded.strategy_id)
    )
    assert response.status_code == 201

    order = (await session.execute(select(Order))).scalar_one()
    fills = list((await session.execute(select(Fill))).scalars())
    assert order.strategy_id == seeded.strategy_id
    assert len(fills) == 1
    assert fills[0].quantity == order.filled_quantity

    positions = await client.get("/api/v1/execution/positions")
    assert positions.status_code == 200
    payload = positions.json()
    assert payload["totals"]["positions"] == 1
    item = payload["items"][0]
    assert item["inst_id"] == "BTC-USDT-SWAP"
    assert item["position_side"] == "long"
    assert item["quantity"] == "0.5"
    assert item["average_price"] == "100"


async def test_paper_order_idempotent_via_http(client, session) -> None:
    seeded = await seed_execution_strategy(session)
    payload = _payload(seeded.strategy_id) | {"client_order_id": "paper-idem"}

    first = await client.post("/api/v1/execution/paper/orders", json=payload)
    second = await client.post("/api/v1/execution/paper/orders", json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    orders = list((await session.execute(select(Order))).scalars())
    assert len(orders) == 1


async def test_paper_reduce_only_never_over_fills() -> None:
    from app.execution.paper import PaperTradingSource
    from app.ports.private import OrderRequest

    source = PaperTradingSource(quote_provider=_const_price, chunks=(Decimal("1"),))
    await source.place_order(
        OrderRequest(
            inst_id="BTC-USDT-SWAP",
            side="sell",
            position_side="long",
            order_type="market",
            quantity=Decimal("2"),
            price=None,
            client_order_id="reduce-without-position",
            reduce_only=True,
        )
    )
    snapshot = await source.fetch_order(
        inst_id="BTC-USDT-SWAP", client_order_id="reduce-without-position"
    )
    assert snapshot is not None
    assert snapshot.filled_quantity == 0
    assert await source.fetch_positions() == []


async def _const_price(inst_id: str):
    return Decimal("100")

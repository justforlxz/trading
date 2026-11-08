"""自动止损：触发平仓单、写 risk_event、不经过策略审批、不重复下单。"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.execution import models, service, stops
from app.market.models import Candle
from app.risk.models import RiskEvent
from tests.execution.conftest import seed_execution_strategy


async def _open_long(session, seeded, client_order_id: str = "entry-1") -> dict:
    body, _ = await service.submit_order(
        session,
        strategy_id=seeded.strategy_id,
        inst_id="BTC-USDT-SWAP",
        side="buy",
        position_side="long",
        quantity=Decimal("1"),
        client_order_id=client_order_id,
        mode="paper",
    )
    if body["state"] != "filled":
        body = await service.poll_order(session, body["id"])
    return body


async def test_stop_triggers_close_order_and_risk_event(session, monkeypatch) -> None:
    seeded = await seed_execution_strategy(session)
    await _open_long(session, seeded)
    position = (await session.execute(select(models.Position))).scalar_one()
    assert position.quantity == Decimal("1")

    session.add(
        Candle(
            instrument_id=seeded.instrument_ids["BTC-USDT-SWAP"],
            bar="1d",
            open_time=datetime.now(tz=UTC) - timedelta(minutes=5),
            open=Decimal("91"),
            high=Decimal("91"),
            low=Decimal("89"),
            close=Decimal("90"),
            vol=Decimal("1"),
            vol_ccy=Decimal("1"),
            vol_ccy_quote=Decimal("90"),
            confirm=True,
            source="test",
        )
    )
    await session.commit()

    def _no_risk(*args, **kwargs):  # pragma: no cover - 命中即失败
        raise AssertionError("止损路径不得调用策略审批")

    monkeypatch.setattr("app.execution.stops.risk_service.evaluate", _no_risk)

    result = await stops.evaluate(session)
    assert result["evaluated"] == 1
    assert len(result["triggered"]) == 1
    trigger = result["triggered"][0]
    order = trigger["order"]
    assert order["intent"] == "stop"
    assert order["side"] == "sell"
    assert order["reduce_only"] is True
    assert order["quantity"] == "1"
    assert trigger["risk_event_id"] is not None

    event = (
        await session.execute(select(RiskEvent).where(RiskEvent.kind == "stop_trigger"))
    ).scalar_one()
    assert event.strategy_id == seeded.strategy_id
    assert event.action == "close"

    stored = await session.get(models.Order, order["id"])
    assert stored is not None
    assert stored.risk_event_id == event.id


async def test_stop_does_not_duplicate_while_order_is_open(session, monkeypatch) -> None:
    seeded = await seed_execution_strategy(session)
    await _open_long(session, seeded)
    session.add(
        Candle(
            instrument_id=seeded.instrument_ids["BTC-USDT-SWAP"],
            bar="1d",
            open_time=datetime.now(tz=UTC) - timedelta(minutes=5),
            open=Decimal("90"),
            high=Decimal("90"),
            low=Decimal("90"),
            close=Decimal("90"),
            vol=Decimal("1"),
            vol_ccy=Decimal("1"),
            vol_ccy_quote=Decimal("90"),
            confirm=True,
            source="test",
        )
    )
    await session.commit()

    first = await stops.evaluate(session)
    second = await stops.evaluate(session)

    assert len(first["triggered"]) == 1
    assert second["triggered"] == []
    assert second["skipped"][0]["reason"] == "stop_order_open"

    stop_orders = list(
        (await session.execute(select(models.Order).where(models.Order.intent == "stop"))).scalars()
    )
    assert len(stop_orders) == 1


async def test_stop_position_closed_after_fill(session) -> None:
    seeded = await seed_execution_strategy(session)
    await _open_long(session, seeded)
    session.add(
        Candle(
            instrument_id=seeded.instrument_ids["BTC-USDT-SWAP"],
            bar="1d",
            open_time=datetime.now(tz=UTC) - timedelta(minutes=5),
            open=Decimal("80"),
            high=Decimal("80"),
            low=Decimal("80"),
            close=Decimal("80"),
            vol=Decimal("1"),
            vol_ccy=Decimal("1"),
            vol_ccy_quote=Decimal("80"),
            confirm=True,
            source="test",
        )
    )
    await session.commit()

    result = await stops.evaluate(session)
    order_id = result["triggered"][0]["order"]["id"]
    await service.poll_order(session, order_id)

    position = (
        await session.execute(select(models.Position).where(models.Position.quantity > 0))
    ).scalar_one_or_none()
    assert position is None

"""风控入口：拒绝落库、紧急停止与两类标的的端到端链路。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core import OrderIntent
from app.instrument import sync_instruments
from app.risk import (
    RiskContext,
    RiskEngine,
    RiskLimits,
    TradeRequest,
    list_risk_events,
)
from app.risk import service as risk_service
from tests.factories.instruments import make_ref, make_swap_ref

D = Decimal
NOW = datetime(2026, 11, 13, 2, 0, tzinfo=UTC)


def spot_request(**overrides: object) -> TradeRequest:
    values: dict[str, object] = {
        "instance_id": "si_1",
        "inst_id": "XAAPL-USDT",
        "side": "buy",
        "order_type": "limit",
        "qty": D("10"),
        "price": D("100"),
        "ts": NOW,
    }
    values.update(overrides)
    return TradeRequest(**values)  # type: ignore[arg-type]


def swap_request(**overrides: object) -> TradeRequest:
    values: dict[str, object] = {
        "instance_id": "si_1",
        "inst_id": "AAPL-USDT-SWAP",
        "side": "buy",
        "order_type": "limit",
        "qty": D("1"),
        "price": D("100"),
        "leverage": D("3"),
        "funding_rate": D("0"),
        "liquidation_price": D("80"),
        "ts": NOW,
    }
    values.update(overrides)
    return TradeRequest(**values)  # type: ignore[arg-type]


def context(**overrides: object) -> RiskContext:
    values: dict[str, object] = {
        "equity": D("10000"),
        "available_balance": D("10000"),
    }
    values.update(overrides)
    return RiskContext(**values)  # type: ignore[arg-type]


@pytest.fixture()
def seeded(client: TestClient) -> TestClient:
    """两类标的都走业务同步路径写入，风控入口按标的行取交易规则。"""

    sync_instruments([make_ref(), make_swap_ref()])
    return client


def test_rejection_writes_events_and_never_builds_an_order_intent(
    seeded: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(request: TradeRequest) -> OrderIntent:
        raise AssertionError("风控拒绝时不允许构造 OrderIntent")

    monkeypatch.setattr(risk_service, "_build_intent", explode)

    result = RiskEngine().authorize(spot_request(qty=D("100")), context())

    assert not result.allowed
    assert result.intent is None
    assert {"order_amount_ratio", "instrument_weight"} <= {item.rule for item in result.violations}

    rows, total = list_risk_events(instance_id="si_1")
    assert total == len(result.violations)
    assert {row.rule for row in rows} >= {"order_amount_ratio", "instrument_weight"}
    assert all(row.detail for row in rows)
    assert all(row.created_at == NOW for row in rows)


def test_passing_signal_builds_an_order_intent_without_events(seeded: TestClient) -> None:
    result = RiskEngine().authorize(spot_request(), context())

    assert result.allowed
    assert isinstance(result.intent, OrderIntent)
    assert result.intent.inst_id == "XAAPL-USDT"
    assert result.intent.qty == D("10")
    assert result.intent.price == D("100")

    rows, total = list_risk_events()
    assert rows == ()
    assert total == 0


def test_emergency_stop_blocks_new_positions_and_leaves_reduce_only_alone(
    seeded: TestClient,
) -> None:
    engine = RiskEngine()
    engine.set_emergency_stop(True)

    blocked = engine.authorize(spot_request(), context())
    reduced = engine.authorize(spot_request(side="sell", reduce_only=True), context())

    assert not blocked.allowed
    assert blocked.intent is None
    assert {item.rule for item in blocked.violations} == {"emergency_stop"}
    assert reduced.allowed
    assert isinstance(reduced.intent, OrderIntent)

    rows, total = list_risk_events()
    assert total == 1
    assert rows[0].rule == "emergency_stop"


@pytest.mark.parametrize(
    ("label", "trade_request", "risk_context", "expected_allowed", "expected_rules"),
    [
        (
            "SPOT 通过",
            spot_request(),
            context(),
            True,
            set(),
        ),
        (
            "SPOT 拒绝",
            spot_request(),
            context(available_balance=D("500")),
            False,
            {"available_balance"},
        ),
        (
            "SWAP 通过",
            swap_request(),
            context(),
            True,
            set(),
        ),
        (
            "SWAP 拒绝",
            swap_request(funding_rate=D("0.05"), liquidation_price=D("95")),
            context(),
            False,
            {"funding_rate", "liquidation_distance"},
        ),
    ],
    ids=["spot-pass", "spot-reject", "swap-pass", "swap-reject"],
)
def test_end_to_end_for_both_categories(
    seeded: TestClient,
    label: str,
    trade_request: TradeRequest,
    risk_context: RiskContext,
    expected_allowed: bool,
    expected_rules: set[str],
) -> None:
    result = RiskEngine().authorize(trade_request, risk_context)

    assert result.allowed is expected_allowed, label
    if expected_allowed:
        assert result.intent is not None
        assert result.violations == ()
    else:
        assert result.intent is None
        assert {item.rule for item in result.violations} == expected_rules


def test_limits_cannot_raise_hard_leverage_cap() -> None:
    from app.core import ValidationError

    with pytest.raises(ValidationError):
        replace(RiskLimits(), max_leverage=D("11"))

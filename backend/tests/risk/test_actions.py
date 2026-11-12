"""处置动作：覆盖待批准申请、紧急停止与事件幂等。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core import ValidationError
from app.db import session_scope
from app.instrument import sync_instruments
from app.portfolio import (
    PENDING,
    SUPERSEDED,
    TargetLegRecord,
    TargetRecord,
    create_adjustment,
    list_adjustments,
)
from app.portfolio.model import PortfolioAdjustmentRow
from app.risk import (
    DisposalContext,
    DisposalRequest,
    RiskContext,
    RiskEngine,
    Severity,
    TradeRequest,
    dispose,
    list_risk_events,
    plan,
)
from app.risk.disposal import RULE_DRAWDOWN, RULE_LIQUIDATION
from app.strategy import create_instance
from tests.factories.instruments import make_ref, make_swap_ref

D = Decimal
NOW = datetime(2026, 11, 13, 2, 0, tzinfo=UTC)
SPOT_ID = "XAAPL-USDT"
OTHER_SPOT_ID = "BTC-USDT"
SWAP_ID = "AAPL-USDT-SWAP"
OTHER_SWAP_ID = "BTC-USDT-SWAP"


@pytest.fixture()
def seeded(client: TestClient) -> dict[str, str]:
    """两类标的各一组，且一个实例内不混同一产品的两种形态。"""

    sync_instruments(
        [
            make_ref(),
            make_ref(inst_id=OTHER_SPOT_ID, base_ccy="BTC", inst_category="1"),
            make_swap_ref(),
            make_swap_ref(inst_id=OTHER_SWAP_ID, ct_val_ccy="BTC", inst_category="1"),
        ]
    )
    spot = create_instance(
        strategy_id="relative_value",
        name="现货配对",
        bar="1d",
        inst_ids=[SPOT_ID, OTHER_SPOT_ID],
    )
    swap = create_instance(
        strategy_id="relative_value",
        name="永续配对",
        bar="1d",
        inst_ids=[SWAP_ID, OTHER_SWAP_ID],
    )
    return {"spot": spot.instance_id, "swap": swap.instance_id}


def target(inst_id: str, inst_type: str, weight: str = "0.5") -> TargetRecord:
    return TargetRecord(
        legs=(
            TargetLegRecord(
                inst_id=inst_id,
                inst_type=inst_type,
                direction="long",
                target_weight=D(weight),
            ),
        ),
        net_exposure=D(weight),
    )


def spot_medium_plan():
    return plan(
        RULE_DRAWDOWN,
        DisposalContext(
            inst_type="SPOT",
            inst_id=SPOT_ID,
            product_key="AAPL",
            equity=D("10000"),
            drawdown=D("0.10"),
        ),
    )


def test_medium_disposal_overrides_pending_without_any_approval(
    client: TestClient, seeded: dict[str, str]
) -> None:
    instance_id = seeded["spot"]
    adjustment = create_adjustment(
        instance_id=instance_id,
        requested_by="alice",
        target=target(SPOT_ID, "SPOT"),
    )

    outcome = dispose(
        spot_medium_plan(),
        DisposalRequest(
            instance_id=instance_id,
            position_side="long",
            position_qty=D("10"),
            at=NOW,
        ),
    )

    assert len(outcome.intents) == 1
    intent = outcome.intents[0]
    assert intent.inst_id == SPOT_ID
    assert intent.side == "sell"
    assert intent.qty == D("5")
    assert intent.reduce_only is False  # 现货没有「只减仓」
    assert outcome.overridden_approval_ids == (adjustment.adjustment_id,)
    assert outcome.event_ids

    records, _ = list_adjustments()
    stored = next(item for item in records if item.adjustment_id == adjustment.adjustment_id)
    assert stored.status == SUPERSEDED

    events, total = list_risk_events(instance_id=instance_id)
    assert total == 1
    event = events[0]
    assert event.severity == Severity.MEDIUM.value
    assert event.action == "reduce"
    assert event.target_product_key == "AAPL"
    assert event.overridden_approval_id == adjustment.adjustment_id

    listed = client.get("/api/portfolio/adjustments")
    assert listed.status_code == 200, listed.text
    listed_row = next(
        item for item in listed.json()["items"] if item["adjustment_id"] == adjustment.adjustment_id
    )
    assert listed_row["status"] == SUPERSEDED


def test_override_stays_scoped_to_the_disposed_instrument(
    seeded: dict[str, str],
) -> None:
    instance_id = seeded["spot"]
    spot = create_adjustment(
        instance_id=instance_id,
        requested_by="alice",
        target=target(SPOT_ID, "SPOT"),
    )
    other = create_adjustment(
        instance_id=instance_id,
        requested_by="alice",
        target=target(OTHER_SPOT_ID, "SPOT"),
    )

    outcome = dispose(
        spot_medium_plan(),
        DisposalRequest(
            instance_id=instance_id,
            position_side="long",
            position_qty=D("10"),
            at=NOW,
        ),
    )

    assert outcome.overridden_approval_ids == (spot.adjustment_id,)
    records, _ = list_adjustments()
    statuses = {item.adjustment_id: item.status for item in records}
    assert statuses[spot.adjustment_id] == SUPERSEDED
    assert statuses[other.adjustment_id] == PENDING


def test_same_instrument_disposal_writes_an_event_for_each_instance(
    seeded: dict[str, str],
) -> None:
    second = create_instance(
        strategy_id="relative_value",
        name="第二个永续策略",
        bar="1d",
        inst_ids=[SWAP_ID, OTHER_SWAP_ID],
    )
    medium = plan(
        RULE_DRAWDOWN,
        DisposalContext(
            inst_type="SWAP",
            inst_id=SWAP_ID,
            product_key="AAPL",
            equity=D("10000"),
            drawdown=D("0.10"),
        ),
    )

    instance_ids = (seeded["swap"], second.instance_id)
    for instance_id in instance_ids:
        outcome = dispose(
            medium,
            DisposalRequest(
                instance_id=instance_id,
                position_side="short",
                position_qty=D("4"),
                at=NOW,
            ),
        )
        assert len(outcome.event_ids) == 1

    for instance_id in instance_ids:
        events, total = list_risk_events(instance_id=instance_id)
        assert total == 1
        assert events[0].inst_id == SWAP_ID


def test_failed_disposal_rolls_back_emergency_stop_and_events(
    seeded: dict[str, str],
) -> None:
    instance_id = seeded["spot"]
    with session_scope() as session:
        session.add(
            PortfolioAdjustmentRow(
                adjustment_id="adj_bad_target",
                instance_id=instance_id,
                status=PENDING,
                requested_by="alice",
                requested_at=NOW,
                target_json="{not-json",
            )
        )
    engine = RiskEngine()
    severe = plan(
        RULE_DRAWDOWN,
        DisposalContext(
            inst_type="SPOT",
            inst_id=SPOT_ID,
            product_key="AAPL",
            equity=D("10000"),
            drawdown=D("0.30"),
        ),
    )

    with pytest.raises(ValidationError):
        dispose(
            severe,
            DisposalRequest(
                instance_id=instance_id,
                position_side="long",
                position_qty=D("10"),
                at=NOW,
                engine=engine,
            ),
        )

    assert engine.halted is False
    _, total = list_risk_events(instance_id=instance_id)
    assert total == 0


def test_halt_all_blocks_later_signals_through_t6_1(seeded: dict[str, str]) -> None:
    instance_id = seeded["spot"]
    engine = RiskEngine()
    severe = plan(
        RULE_DRAWDOWN,
        DisposalContext(
            inst_type="SPOT",
            inst_id=SPOT_ID,
            product_key="AAPL",
            equity=D("10000"),
            drawdown=D("0.20"),
        ),
    )

    outcome = dispose(
        severe,
        DisposalRequest(
            instance_id=instance_id,
            position_side="long",
            position_qty=D("10"),
            at=NOW,
            engine=engine,
        ),
    )

    assert outcome.halted is True
    assert engine.halted is True

    blocked = engine.authorize(
        TradeRequest(
            instance_id=instance_id,
            inst_id=SPOT_ID,
            side="buy",
            order_type="limit",
            qty=D("1"),
            price=D("100"),
            ts=NOW,
        ),
        RiskContext(equity=D("10000"), available_balance=D("10000")),
    )

    assert blocked.allowed is False
    assert blocked.intent is None
    assert {item.rule for item in blocked.violations} == {"emergency_stop"}
    events, _ = list_risk_events(instance_id=instance_id)
    assert "emergency_stop" in {item.rule for item in events}


def test_severe_halt_without_a_position_still_halts_and_records(seeded: dict[str, str]) -> None:
    instance_id = seeded["spot"]
    engine = RiskEngine()
    severe = plan(
        RULE_DRAWDOWN,
        DisposalContext(
            inst_type="SPOT",
            inst_id=SPOT_ID,
            product_key="AAPL",
            equity=D("10000"),
            drawdown=D("0.20"),
        ),
    )

    outcome = dispose(
        severe,
        DisposalRequest(
            instance_id=instance_id,
            position_side="long",
            position_qty=D("0"),
            at=NOW,
            engine=engine,
        ),
    )

    assert outcome.intents == ()
    assert outcome.halted is True
    assert engine.halted is True
    events, total = list_risk_events(instance_id=instance_id)
    assert total == 1
    assert events[0].rule == RULE_DRAWDOWN


def test_repeated_disposal_in_the_same_window_writes_one_event(
    seeded: dict[str, str],
) -> None:
    instance_id = seeded["spot"]
    request = DisposalRequest(
        instance_id=instance_id,
        position_side="long",
        position_qty=D("10"),
        at=NOW,
    )

    first = dispose(spot_medium_plan(), request)
    second = dispose(spot_medium_plan(), request)

    assert len(first.event_ids) == 1
    assert second.event_ids == ()
    _, total = list_risk_events(instance_id=instance_id)
    assert total == 1


def test_disposal_event_can_be_marked_resolved(client: TestClient, seeded: dict[str, str]) -> None:
    instance_id = seeded["spot"]
    outcome = dispose(
        spot_medium_plan(),
        DisposalRequest(
            instance_id=instance_id,
            position_side="long",
            position_qty=D("10"),
            at=NOW,
        ),
    )
    event_id = outcome.event_ids[0]

    resolved = client.patch(f"/api/risk/events/{event_id}/resolve")
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["event_id"] == event_id
    assert body["resolved_at"] is not None
    assert body["severity"] == "medium"
    assert body["action"] == "reduce"

    again = client.patch(f"/api/risk/events/{event_id}/resolve")
    assert again.status_code == 200, again.text
    assert again.json()["resolved_at"] == body["resolved_at"]

    missing = client.patch("/api/risk/events/re_missing/resolve")
    assert missing.status_code == 404


def test_severe_swap_liquidation_builds_reduce_only_intent(
    seeded: dict[str, str],
) -> None:
    instance_id = seeded["swap"]
    severe = plan(
        RULE_LIQUIDATION,
        DisposalContext(
            inst_type="SWAP",
            inst_id=SWAP_ID,
            product_key="AAPL",
            equity=D("10000"),
            liquidation_distance=D("0.03"),
        ),
    )

    outcome = dispose(
        severe,
        DisposalRequest(
            instance_id=instance_id,
            position_side="short",
            position_qty=D("4"),
            at=NOW,
        ),
    )

    assert outcome.plan.severity is Severity.SEVERE
    assert len(outcome.intents) == 1
    intent = outcome.intents[0]
    assert intent.side == "buy"
    assert intent.qty == D("4")
    assert intent.pos_side == "short"
    assert intent.reduce_only is True


def test_severity_escalation_in_the_same_window_is_recorded(
    seeded: dict[str, str],
) -> None:
    instance_id = seeded["spot"]
    request = DisposalRequest(
        instance_id=instance_id,
        position_side="long",
        position_qty=D("10"),
        at=NOW,
    )
    severe = plan(
        RULE_DRAWDOWN,
        DisposalContext(
            inst_type="SPOT",
            inst_id=SPOT_ID,
            product_key="AAPL",
            equity=D("10000"),
            drawdown=D("0.20"),
        ),
    )

    first = dispose(spot_medium_plan(), request)
    escalated = dispose(severe, request)

    assert len(first.event_ids) == 1
    assert len(escalated.event_ids) == 1
    events, total = list_risk_events(instance_id=instance_id)
    assert total == 2
    assert {event.severity for event in events} == {"medium", "severe"}

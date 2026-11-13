"""手动持仓纯函数：已知答案覆盖加权成本、部分卖出、清仓、超卖与更正。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core import InvariantViolation, UnprocessableEntity, ValidationError
from app.positions import LedgerTrade, apply_trade, replay_trades

OPEN_AT = datetime(2026, 11, 13, 1, 0, tzinfo=UTC)


def test_open_sets_quantity_and_cost() -> None:
    effect = apply_trade(
        side="long",
        action="open",
        current_quantity=Decimal(0),
        current_avg_cost=Decimal(0),
        quantity=Decimal("10"),
        price=Decimal("100"),
    )

    assert effect.quantity == Decimal("10")
    assert effect.avg_cost == Decimal("100")
    assert effect.status == "open"
    assert effect.realized_pnl is None


def test_add_uses_weighted_cost_and_capitalizes_fee() -> None:
    effect = apply_trade(
        side="long",
        action="add",
        current_quantity=Decimal("10"),
        current_avg_cost=Decimal("100"),
        quantity=Decimal("5"),
        price=Decimal("110"),
        fee=Decimal("1"),
    )

    assert effect.quantity == Decimal("15")
    assert effect.avg_cost == Decimal("103.4")
    assert effect.status == "open"
    assert effect.realized_pnl is None


def test_partial_reduce_keeps_average_cost_and_realizes_pnl() -> None:
    effect = apply_trade(
        side="long",
        action="reduce",
        current_quantity=Decimal("10"),
        current_avg_cost=Decimal("103.4"),
        quantity=Decimal("5"),
        price=Decimal("120"),
        fee=Decimal("0.5"),
    )

    assert effect.quantity == Decimal("5")
    assert effect.avg_cost == Decimal("103.4")
    assert effect.status == "open"
    assert effect.realized_pnl == Decimal("82.5")


def test_reduce_to_zero_closes_the_position() -> None:
    effect = apply_trade(
        side="long",
        action="reduce",
        current_quantity=Decimal("5"),
        current_avg_cost=Decimal("103.4"),
        quantity=Decimal("5"),
        price=Decimal("120"),
        fee=Decimal("0"),
    )

    assert effect.quantity == Decimal("0")
    assert effect.status == "closed"
    assert effect.realized_pnl == Decimal("83")


def test_close_requires_matching_quantity() -> None:
    with pytest.raises(UnprocessableEntity):
        apply_trade(
            side="long",
            action="close",
            current_quantity=Decimal("5"),
            current_avg_cost=Decimal("100"),
            quantity=Decimal("4"),
            price=Decimal("110"),
        )


def test_reduce_more_than_current_quantity_is_422() -> None:
    with pytest.raises(UnprocessableEntity):
        apply_trade(
            side="long",
            action="reduce",
            current_quantity=Decimal("5"),
            current_avg_cost=Decimal("100"),
            quantity=Decimal("6"),
            price=Decimal("110"),
        )


def test_non_positive_inputs_are_validation_errors() -> None:
    with pytest.raises(ValidationError):
        apply_trade(
            side="long",
            action="add",
            current_quantity=Decimal("5"),
            current_avg_cost=Decimal("100"),
            quantity=Decimal("0"),
            price=Decimal("110"),
        )
    with pytest.raises(ValidationError):
        apply_trade(
            side="long",
            action="add",
            current_quantity=Decimal("5"),
            current_avg_cost=Decimal("100"),
            quantity=Decimal("1"),
            price=Decimal("-1"),
        )


def test_correct_sets_absolute_quantity_and_cost_without_pnl() -> None:
    effect = apply_trade(
        side="long",
        action="correct",
        current_quantity=Decimal("5"),
        current_avg_cost=Decimal("100"),
        quantity=Decimal("8"),
        price=Decimal("98"),
    )

    assert effect.quantity == Decimal("8")
    assert effect.avg_cost == Decimal("98")
    assert effect.realized_pnl is None


def test_replay_returns_post_trade_state_in_chronological_order() -> None:
    trades = [
        _trade("t1", "open", "10", "100", at=OPEN_AT),
        _trade("t2", "add", "5", "110", fee="1", at=OPEN_AT + timedelta(minutes=1)),
        _trade("t3", "reduce", "5", "120", fee="0.5", at=OPEN_AT + timedelta(minutes=2)),
    ]

    projections = replay_trades(trades, side="long")

    assert [row.quantity_after for row in projections] == [
        Decimal("10"),
        Decimal("15"),
        Decimal("10"),
    ]
    assert projections[1].avg_cost_after == Decimal("103.4")
    assert projections[2].realized_pnl == Decimal("82.5")


def test_replay_rejects_a_ledger_that_cannot_have_happened() -> None:
    trades = [
        _trade("t1", "open", "5", "100", at=OPEN_AT),
        _trade("t2", "reduce", "6", "100", at=OPEN_AT + timedelta(minutes=1)),
    ]

    with pytest.raises(InvariantViolation):
        replay_trades(trades, side="long")


def test_short_partial_reduce_realizes_profit_when_price_falls() -> None:
    effect = apply_trade(
        side="short",
        action="reduce",
        current_quantity=Decimal("10"),
        current_avg_cost=Decimal("100"),
        quantity=Decimal("5"),
        price=Decimal("90"),
        fee=Decimal("0.5"),
    )

    assert effect.quantity == Decimal("5")
    assert effect.avg_cost == Decimal("100")
    assert effect.status == "open"
    assert effect.realized_pnl == Decimal("49.5")


def test_short_partial_reduce_realizes_loss_when_price_rises() -> None:
    effect = apply_trade(
        side="short",
        action="reduce",
        current_quantity=Decimal("10"),
        current_avg_cost=Decimal("100"),
        quantity=Decimal("4"),
        price=Decimal("115"),
        fee=Decimal("1"),
    )

    assert effect.quantity == Decimal("6")
    assert effect.realized_pnl == Decimal("-61")


def test_short_close_matches_the_hand_calculation() -> None:
    effect = apply_trade(
        side="short",
        action="close",
        current_quantity=Decimal("10"),
        current_avg_cost=Decimal("100"),
        quantity=Decimal("10"),
        price=Decimal("88"),
        fee=Decimal("2"),
    )

    assert effect.quantity == Decimal("0")
    assert effect.status == "closed"
    assert effect.realized_pnl == Decimal("118")


def test_replay_uses_the_short_side_for_realized_pnl() -> None:
    trades = [
        _trade("t1", "open", "10", "100", at=OPEN_AT),
        _trade("t2", "reduce", "5", "90", fee="0.5", at=OPEN_AT + timedelta(minutes=1)),
        _trade("t3", "close", "5", "95", at=OPEN_AT + timedelta(minutes=2)),
    ]

    projections = replay_trades(trades, side="short")

    assert projections[1].realized_pnl == Decimal("49.5")
    assert projections[2].realized_pnl == Decimal("25")


def test_unknown_side_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        apply_trade(
            side="flat",
            action="reduce",
            current_quantity=Decimal("5"),
            current_avg_cost=Decimal("100"),
            quantity=Decimal("1"),
            price=Decimal("110"),
        )


def _trade(
    trade_id: str,
    action: str,
    quantity: str,
    price: str,
    *,
    fee: str = "0",
    at: datetime,
) -> LedgerTrade:
    return LedgerTrade(
        trade_id=trade_id,
        action=action,
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal(fee),
        occurred_at=at,
        created_at=at,
    )

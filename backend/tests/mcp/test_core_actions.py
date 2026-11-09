"""`plan_action` 的纯函数单测：动作 -> 订单参数必须可断言。"""

from decimal import Decimal

import pytest

from app.mcp.core.actions import ActionError, parse_quantity, plan_action


def test_open_buy_maps_to_long_entry() -> None:
    plan = plan_action("open", side="buy", quantity="2")
    assert (plan.side, plan.position_side) == ("buy", "long")
    assert plan.quantity == Decimal("2")
    assert (plan.intent, plan.reduce_only) == ("entry", False)


def test_open_sell_maps_to_short_entry() -> None:
    plan = plan_action("open", side="sell", quantity=Decimal("1.5"))
    assert (plan.side, plan.position_side) == ("sell", "short")


def test_open_accepts_position_side_only() -> None:
    plan = plan_action("open", position_side="short", quantity="3")
    assert (plan.side, plan.position_side) == ("sell", "short")


def test_side_and_position_side_must_agree() -> None:
    with pytest.raises(ActionError) as caught:
        plan_action("open", side="buy", position_side="short", quantity="1")
    assert caught.value.code == "action_side_conflict"


def test_action_must_be_known() -> None:
    with pytest.raises(ActionError) as caught:
        plan_action("liquidate", side="buy", quantity="1")
    assert caught.value.code == "invalid_action"


def test_open_requires_positive_quantity() -> None:
    with pytest.raises(ActionError) as caught:
        plan_action("open", side="buy", quantity="0")
    assert caught.value.code == "action_quantity_required"


def test_open_requires_a_direction() -> None:
    with pytest.raises(ActionError) as caught:
        plan_action("open", quantity="1")
    assert caught.value.code == "action_side_required"


def test_increase_requires_an_existing_position() -> None:
    with pytest.raises(ActionError) as caught:
        plan_action("increase", side="buy", quantity="1", available=Decimal("0"))
    assert caught.value.code == "no_position"


def test_reduce_flips_side_and_caps_at_position() -> None:
    plan = plan_action("reduce", position_side="long", quantity="1", available=Decimal("4"))
    assert (plan.side, plan.position_side) == ("sell", "long")
    assert plan.quantity == Decimal("1")
    assert (plan.intent, plan.reduce_only) == ("exit", True)

    with pytest.raises(ActionError) as caught:
        plan_action("reduce", position_side="long", quantity="9", available=Decimal("4"))
    assert caught.value.code == "exceeds_position"


def test_close_always_uses_the_whole_position() -> None:
    plan = plan_action("close", position_side="short", available=Decimal("3"))
    assert (plan.side, plan.position_side) == ("buy", "short")
    assert plan.quantity == Decimal("3")
    assert plan.reduce_only is True

    with pytest.raises(ActionError) as caught:
        plan_action("close", position_side="short", quantity="1", available=Decimal("3"))
    assert caught.value.code == "action_quantity_mismatch"


def test_stop_uses_stop_intent_and_full_position() -> None:
    plan = plan_action("stop", position_side="long", available=Decimal("2"))
    assert (plan.intent, plan.reduce_only) == ("stop", True)
    assert plan.quantity == Decimal("2")


@pytest.mark.parametrize("action", ["reduce", "close", "stop"])
def test_reduce_family_requires_position_side(action: str) -> None:
    with pytest.raises(ActionError) as caught:
        plan_action(action, available=Decimal("1"))
    assert caught.value.code == "action_position_side_required"


@pytest.mark.parametrize("action", ["reduce", "close", "stop"])
def test_reduce_family_requires_an_open_position(action: str) -> None:
    with pytest.raises(ActionError) as caught:
        plan_action(action, position_side="long", available=Decimal("0"))
    assert caught.value.code == "no_position"


@pytest.mark.parametrize("value", ["abc", "0", "-1", "nan", "Infinity", None, True])
def test_parse_quantity_rejects_non_positive_and_non_finite(value: object) -> None:
    assert parse_quantity(value) is None


def test_parse_quantity_accepts_numbers_and_strings() -> None:
    assert parse_quantity(2) == Decimal("2")
    assert parse_quantity("1.25") == Decimal("1.25")
    assert parse_quantity(1.5) == Decimal("1.5")

"""按类别交易规则集合：逐格断言取值，并用注册第三类别证明扩展不碰已有类别。"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import FrozenInstanceError, fields
from decimal import Decimal

import pytest

from app.core import ValidationError
from app.instrument import TradingRules, trading_rules
from app.instrument import rules as rules_module
from app.instrument.model import SPOT, SWAP
from app.instrument.rules import register_rules

#: 期望值表：类别 → 字段 → 取值。与冻结的规则集合逐格对照，任何一格漂移都会红。
EXPECTED: dict[str, dict[str, object]] = {
    SPOT: {
        "tick_size_required": True,
        "min_order_size_required": True,
        "max_leverage": None,
        "has_margin": False,
        "has_funding": False,
        "funding_interval_hours": None,
        "session_kind": "crypto_24_7",
        # 两类都含 preopen：现货列表同样会出现预上线记录，理由见 rules.py。
        "state_kinds": frozenset({"live", "suspend", "preopen"}),
        "has_position_endpoint": False,
        "qty_unit": "base",
    },
    SWAP: {
        "tick_size_required": True,
        "min_order_size_required": True,
        # 永续不设本地上限：可用杠杆取标的自身 `maxLever`（见 TradingRules 文档）。
        "max_leverage": None,
        "has_margin": True,
        "has_funding": True,
        "funding_interval_hours": 8,
        "session_kind": "equity",
        "state_kinds": frozenset({"live", "suspend", "preopen"}),
        "has_position_endpoint": True,
        "qty_unit": "contract",
    },
}

#: 只在测试期存在的第三类别：取值故意与已注册的两个类别都不同。
TEST_ONLY = "TEST_ONLY_FUTURE"
TEST_ONLY_RULES = TradingRules(
    tick_size_required=False,
    min_order_size_required=False,
    max_leverage=Decimal("2.5"),
    has_margin=True,
    has_funding=True,
    funding_interval_hours=4,
    session_kind="equity",
    state_kinds=frozenset({"live", "preopen"}),
    has_position_endpoint=True,
    qty_unit="contract",
)


def _cells(rules: TradingRules) -> dict[str, object]:
    """把规则摊成字段 → 取值，便于逐字段比对。"""

    return {field.name: getattr(rules, field.name) for field in fields(TradingRules)}


@pytest.fixture()
def isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """用例内注册的类别不泄漏出去：注册表在用例开始与结束时被还原。"""

    monkeypatch.setattr(rules_module, "_RULES", dict(rules_module._RULES))
    yield


@pytest.mark.parametrize(("inst_type", "expected"), sorted(EXPECTED.items()))
def test_rule_set_matches_the_frozen_table(inst_type: str, expected: dict[str, object]) -> None:
    """逐格对照：字段名集合与每个字段的取值都必须一致。"""

    actual = trading_rules(inst_type)
    assert {field.name for field in fields(TradingRules)} == set(expected)

    wrong = {
        name: (getattr(actual, name), value)
        for name, value in expected.items()
        if getattr(actual, name) != value
    }
    assert not wrong, f"{inst_type} 的规则取值与冻结表不一致:(实际, 期望)={wrong}"


def test_spot_has_no_margin_no_funding_no_leverage() -> None:
    """现货是全额买入：没有保证金、没有资金费、没有杠杆、没有持仓端点。"""

    rules = trading_rules(SPOT)
    assert not rules.has_margin
    assert not rules.has_funding
    assert not rules.has_position_endpoint
    assert rules.funding_interval_hours is None
    assert rules.max_leverage is None
    assert rules.qty_unit == "base"


def test_swap_has_margin_funding_and_eight_hour_settlement() -> None:
    """永续有保证金与资金费，资金费每 8 小时结算一次，下单数量以张为单位。"""

    rules = trading_rules(SWAP)
    assert rules.has_margin
    assert rules.has_funding
    assert rules.has_position_endpoint
    assert rules.funding_interval_hours == 8
    assert rules.qty_unit == "contract"


def test_rules_are_immutable() -> None:
    """规则是静态常量：拿到手也改不动，避免下游就地改写影响其它调用方。"""

    rules = trading_rules(SPOT)
    with pytest.raises(FrozenInstanceError):
        rules.qty_unit = "contract"  # type: ignore[misc]


@pytest.mark.parametrize(("given", "expected"), [("spot", SPOT), (" Swap ", SWAP)])
def test_category_name_is_normalized(given: str, expected: str) -> None:
    assert trading_rules(given) == trading_rules(expected)


@pytest.mark.parametrize("inst_type", ["", "   ", "FUTURE"])
def test_unregistered_category_raises(inst_type: str) -> None:
    """未注册的类别直接报错，不返回「大概能用」的默认规则。"""

    with pytest.raises(ValidationError):
        trading_rules(inst_type)


def test_new_category_is_reachable_and_leaves_existing_ones_untouched(
    isolated_registry: None,
) -> None:
    """扩展性证明：注册第三类别后能查到它，SPOT 与 SWAP 逐字段一个都没变。"""

    before = {inst_type: trading_rules(inst_type) for inst_type in (SPOT, SWAP)}

    register_rules(TEST_ONLY, TEST_ONLY_RULES)

    assert trading_rules(TEST_ONLY) == TEST_ONLY_RULES
    assert trading_rules(TEST_ONLY.lower()) == TEST_ONLY_RULES
    for inst_type, rules_before in before.items():
        assert _cells(trading_rules(inst_type)) == _cells(rules_before)

"""规则 JSON 的校验：注册表名与展示别名都接受，未知字段和取值一律拒绝。

纯域层用例，不经过 HTTP；接口层的 400 映射在 `tests/api/test_strategy.py`。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core import ValidationError
from app.indicators import list_definitions
from app.strategy.rules import normalize_rule

RULE: dict[str, Any] = {
    "entry": {"all": [{"left": "MA(20)", "op": ">", "right": "MA(60)"}]},
    "exit": {"any": [{"left": "RSI(14)", "op": "<", "right": 70}]},
}


def _rule_with(expression: str) -> dict[str, Any]:
    return {
        "entry": {"all": [{"left": expression, "op": ">", "right": 1}]},
        "exit": {"any": [{"left": "RSI(14)", "op": "<", "right": 70}]},
    }


@pytest.mark.parametrize("definition", list_definitions(), ids=lambda item: item.name)
def test_registry_indicator_names_are_accepted(definition: Any) -> None:
    """注册表里的每个名字都能写进规则；别名表不是第二套允许列表。"""

    args = ",".join(["1"] * len(definition.params))
    expression = f"{definition.name.upper()}({args})"

    rule, _ = normalize_rule(_rule_with(expression), timeframe="1d", direction="long_only")

    assert rule["entry"]["all"][0]["left"] == expression


def test_display_aliases_still_map_to_registry_names() -> None:
    rule, _ = normalize_rule(_rule_with("BOLL(20,2)"), timeframe="1d", direction="long_only")

    assert rule["entry"]["all"][0]["left"] == "BOLL(20,2)"


def test_unknown_indicator_is_rejected() -> None:
    with pytest.raises(ValidationError, match="未注册"):
        normalize_rule(_rule_with("NOPE(20)"), timeframe="1d", direction="long_only")


def test_wrong_parameter_count_is_rejected() -> None:
    with pytest.raises(ValidationError, match="需要 1 个参数"):
        normalize_rule(_rule_with("MA(20,60)"), timeframe="1d", direction="long_only")


def test_normalize_rule_fills_timeframe_and_direction() -> None:
    rule, sizing = normalize_rule(RULE, timeframe="4h", direction="long_short")

    assert rule["timeframe"] == "4h"
    assert rule["direction"] == "long_short"
    assert sizing is None


def test_rule_timeframe_must_match_version() -> None:
    with pytest.raises(ValidationError, match="不一致"):
        normalize_rule({**RULE, "timeframe": "1d"}, timeframe="4h", direction="long_only")

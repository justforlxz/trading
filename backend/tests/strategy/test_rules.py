"""规则 JSON 的校验：条件组结构、指标参数补全、出场附加项与版本字段的一致性。

纯域层用例，不经过 HTTP；接口层的 400 映射在 `tests/api/test_strategy.py`。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core import ValidationError
from app.strategy.rules import normalize_rule

RULE: dict[str, Any] = {
    "entry": {
        "logic": "and",
        "conditions": [
            {
                "left": {"indicator": "sma", "period": 20},
                "op": "gt",
                "right": {"indicator": "sma", "period": 60},
            }
        ],
    },
    "exit": {
        "logic": "or",
        "conditions": [
            {"left": {"indicator": "rsi", "period": 14}, "op": "gt", "right": {"value": 70}}
        ],
        "stop_loss_pct": 5,
    },
}


def _with_entry(*conditions: Any) -> dict[str, Any]:
    return {**RULE, "entry": {"logic": "and", "conditions": list(conditions)}}


def _one_condition(**overrides: Any) -> dict[str, Any]:
    condition = {
        "left": {"indicator": "close"},
        "op": "gt",
        "right": {"value": 100},
    }
    condition.update(overrides)
    return _with_entry(condition)


def test_normalize_rule_fills_timeframe_and_direction() -> None:
    rule, sizing = normalize_rule(RULE, timeframe="4h", direction="long_short")

    assert rule["timeframe"] == "4h"
    assert rule["direction"] == "long_short"
    assert sizing is None


def test_rule_timeframe_must_match_version() -> None:
    with pytest.raises(ValidationError, match="不一致"):
        normalize_rule({**RULE, "timeframe": "1d"}, timeframe="4h", direction="long_only")


def test_rule_direction_must_match_version() -> None:
    with pytest.raises(ValidationError, match="不一致"):
        normalize_rule({**RULE, "direction": "short_only"}, timeframe="4h", direction="long_only")


def test_entry_and_exit_are_both_required() -> None:
    with pytest.raises(ValidationError, match="entry"):
        normalize_rule({"entry": RULE["entry"]}, timeframe="1d", direction="long_only")


def test_unknown_rule_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="未知字段"):
        normalize_rule({**RULE, "unknown": True}, timeframe="1d", direction="long_only")


def test_display_alias_maps_to_registry_name() -> None:
    """`MA` / `BOLL` 这类常见写法落库时归一成注册表名，规则里只有一套名字。"""

    rule, _ = normalize_rule(
        _with_entry(
            {
                "left": {"indicator": "MA", "period": 20},
                "op": "gt",
                "right": {"indicator": "BOLL", "output": "upper", "period": 20, "num_std": 2},
            }
        ),
        timeframe="1d",
        direction="long_only",
    )

    left, right = rule["entry"]["conditions"][0]["left"], rule["entry"]["conditions"][0]["right"]
    assert left["indicator"] == "sma"
    assert right["indicator"] == "bollinger"


def test_parameters_are_filled_from_the_registry() -> None:
    """没写参数时按注册表默认值补全，规则自己就能回答「这套条件用的什么参数」。"""

    rule, _ = normalize_rule(
        _one_condition(
            left={"indicator": "macd", "output": "hist"},
        ),
        timeframe="1d",
        direction="long_only",
    )

    assert rule["entry"]["conditions"][0]["left"] == {
        "indicator": "macd",
        "output": "hist",
        "fast": 12,
        "slow": 26,
        "signal": 9,
    }


def test_single_output_indicator_does_not_need_output() -> None:
    rule, _ = normalize_rule(_one_condition(), timeframe="1d", direction="long_only")

    assert rule["entry"]["conditions"][0]["left"] == {"indicator": "close", "output": "close"}


def test_indicator_outside_the_backtest_list_is_rejected() -> None:
    """注册表里的 EMA 不在用户确认的八个之内，规则里不能写它。"""

    with pytest.raises(ValidationError, match="不在回测可用指标里"):
        normalize_rule(
            _one_condition(left={"indicator": "ema", "period": 20}),
            timeframe="1d",
            direction="long_only",
        )


def test_unknown_indicator_is_rejected() -> None:
    with pytest.raises(ValidationError, match="不在回测可用指标里"):
        normalize_rule(
            _one_condition(left={"indicator": "nope", "period": 20}),
            timeframe="1d",
            direction="long_only",
        )


def test_unknown_parameter_is_rejected() -> None:
    with pytest.raises(ValidationError, match="未知字段"):
        normalize_rule(
            _one_condition(left={"indicator": "sma", "window": 20}),
            timeframe="1d",
            direction="long_only",
        )


def test_out_of_range_parameter_is_rejected() -> None:
    with pytest.raises(ValidationError, match="period"):
        normalize_rule(
            _one_condition(left={"indicator": "rsi", "period": 0}),
            timeframe="1d",
            direction="long_only",
        )


def test_multi_output_indicator_requires_an_output() -> None:
    with pytest.raises(ValidationError, match="output"):
        normalize_rule(
            _one_condition(left={"indicator": "bollinger", "period": 20, "num_std": 2}),
            timeframe="1d",
            direction="long_only",
        )


def test_unknown_output_is_rejected() -> None:
    with pytest.raises(ValidationError, match="output"):
        normalize_rule(
            _one_condition(left={"indicator": "bollinger", "output": "nope"}),
            timeframe="1d",
            direction="long_only",
        )


def test_left_operand_cannot_be_a_constant() -> None:
    with pytest.raises(ValidationError, match="左值"):
        normalize_rule(
            _one_condition(left={"value": 10}),
            timeframe="1d",
            direction="long_only",
        )


def test_right_operand_accepts_a_constant_or_an_indicator() -> None:
    rule, _ = normalize_rule(
        _with_entry(
            {
                "left": {"indicator": "close"},
                "op": "gt",
                "right": {"indicator": "atr", "period": 14},
            }
        ),
        timeframe="1d",
        direction="long_only",
    )

    assert rule["entry"]["conditions"][0]["right"] == {
        "indicator": "atr",
        "output": "atr",
        "period": 14,
    }


def test_operator_must_be_one_of_the_four() -> None:
    with pytest.raises(ValidationError, match="op"):
        normalize_rule(_one_condition(op="!="), timeframe="1d", direction="long_only")


def test_logic_must_be_and_or() -> None:
    with pytest.raises(ValidationError, match="logic"):
        normalize_rule(
            {**RULE, "entry": {"logic": "xor", "conditions": [{"left": {"indicator": "close"}}]}},
            timeframe="1d",
            direction="long_only",
        )


def test_empty_condition_list_is_rejected() -> None:
    with pytest.raises(ValidationError, match="非空数组"):
        normalize_rule(
            {**RULE, "entry": {"logic": "and", "conditions": []}},
            timeframe="1d",
            direction="long_only",
        )


def test_condition_rejects_unknown_field_and_missing_field() -> None:
    with pytest.raises(ValidationError, match="未知字段"):
        normalize_rule(
            _one_condition(extra=1),
            timeframe="1d",
            direction="long_only",
        )
    with pytest.raises(ValidationError, match="缺少字段"):
        normalize_rule(
            _with_entry({"left": {"indicator": "close"}, "op": "gt"}),
            timeframe="1d",
            direction="long_only",
        )


def test_boolean_is_not_a_number() -> None:
    with pytest.raises(ValidationError, match="数值"):
        normalize_rule(
            _one_condition(right={"value": True}),
            timeframe="1d",
            direction="long_only",
        )


def test_exit_extras_are_kept_and_validated() -> None:
    rule, _ = normalize_rule(
        {
            **RULE,
            "exit": {
                **RULE["exit"],
                "take_profit_pct": 12.5,
                "stop_loss_pct": 4,
                "reverse_signal": True,
            },
        },
        timeframe="1d",
        direction="long_only",
    )

    assert rule["exit"]["take_profit_pct"] == 12.5
    assert rule["exit"]["stop_loss_pct"] == 4
    assert rule["exit"]["reverse_signal"] is True

    with pytest.raises(ValidationError, match="必须是正数"):
        normalize_rule(
            {**RULE, "exit": {**RULE["exit"], "stop_loss_pct": 0}},
            timeframe="1d",
            direction="long_only",
        )
    with pytest.raises(ValidationError, match="布尔值"):
        normalize_rule(
            {**RULE, "exit": {**RULE["exit"], "reverse_signal": 1}},
            timeframe="1d",
            direction="long_only",
        )


def test_entry_does_not_accept_exit_extras() -> None:
    with pytest.raises(ValidationError, match="未知字段"):
        normalize_rule(
            {**RULE, "entry": {**RULE["entry"], "take_profit_pct": 10}},
            timeframe="1d",
            direction="long_only",
        )


def test_position_sizing_is_validated_and_returned() -> None:
    sizing = {"type": "equal_weight", "weight": 0.5, "max_positions": 2}

    rule, returned = normalize_rule(
        {**RULE, "position_sizing": sizing},
        timeframe="1d",
        direction="long_only",
    )

    assert returned == sizing
    assert rule["position_sizing"] == sizing

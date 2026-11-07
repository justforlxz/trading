"""验证标准纯函数：默认标准、联合判定与非法输入（AC10）。"""

from decimal import Decimal

import pytest

from app.backtest.criteria import evaluate
from app.backtest.errors import BacktestError

METRICS = {
    "total_return": Decimal("0.12"),
    "max_drawdown": Decimal("0.08"),
    "sharpe": Decimal("1.5"),
}


def test_empty_criteria_uses_default_thresholds() -> None:
    result = evaluate(METRICS, None)
    assert result["default"] is True
    assert result["passed"] is True
    assert [item["name"] for item in result["thresholds"]] == ["total_return", "max_drawdown"]
    assert all("actual" in item and item["passed"] is True for item in result["results"])


def test_passed_is_the_conjunction_of_all_thresholds() -> None:
    failing = evaluate(
        METRICS,
        [
            {"name": "total_return", "op": ">=", "value": "0.2"},
            {"name": "sharpe", "op": ">=", "value": "1"},
        ],
    )
    assert failing["default"] is False
    assert failing["passed"] is False
    assert [item["passed"] for item in failing["results"]] == [False, True]
    assert failing["results"][0]["actual"] == "0.12"
    assert failing["results"][0]["threshold"] == "0.2"

    passing = evaluate(
        METRICS,
        [
            {"name": "total_return", "op": ">=", "value": "0.1"},
            {"name": "max_drawdown", "op": "<=", "value": "0.1"},
        ],
    )
    assert passing["passed"] is True


def test_unknown_metric_and_operator_are_rejected() -> None:
    with pytest.raises(BacktestError) as unknown:
        evaluate(METRICS, [{"name": "nope", "op": ">=", "value": "0"}])
    assert unknown.value.code == "backtest_criteria_unknown_metric"

    with pytest.raises(BacktestError) as bad_op:
        evaluate(METRICS, [{"name": "sharpe", "op": "!=", "value": "0"}])
    assert bad_op.value.code == "backtest_criteria_invalid_op"

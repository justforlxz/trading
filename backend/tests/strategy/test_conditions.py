"""条件表达式：可选指标清单、逐根求值的边界与「不使用未来数据」。

求值是纯函数，用例只造 K 线、不碰数据库与网络；AC2 的三种穿越边界与 AC3 的
「后面暴涨不改变前面」都在这里断言。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.core import Bar, Timeframe
from app.strategy import ConditionIndicator, ConditionOutput, condition_catalog, signal_series
from app.strategy.rules import normalize_rule

_START = datetime(2026, 1, 1, tzinfo=UTC)

#: 用户确认的八个指标，顺序即清单顺序。
_CONFIRMED = [
    ("rsi", "RSI"),
    ("close", "收盘价"),
    ("sma", "MA"),
    ("atr", "ATR"),
    ("volume", "成交量"),
    ("change_24h", "24H 涨跌幅"),
    ("macd", "MACD"),
    ("bollinger", "布林带"),
]


def make_bars(closes: Sequence[Decimal | int | float], *, bar: str = "1h") -> list[Bar]:
    """按收盘价造 K 线，高低价取收盘价上下各 1，成交量固定。"""

    timeframe = Timeframe.parse(bar)
    return [
        Bar(
            inst_id="BTC-USDT",
            timeframe=timeframe,
            open_time=_START + index * timedelta(seconds=timeframe.seconds),
            open=Decimal(str(close)),
            high=Decimal(str(close)) + 1,
            low=Decimal(str(close)) - 1,
            close=Decimal(str(close)),
            volume=Decimal(1000),
            confirm=True,
            source="test",
        )
        for index, close in enumerate(closes)
    ]


def group(*conditions: dict[str, Any], logic: str = "and") -> dict[str, Any]:
    return {"logic": logic, "conditions": list(conditions)}


def close_vs(op: str, right: Any) -> dict[str, Any]:
    return {"left": {"indicator": "close", "output": "close"}, "op": op, "right": right}


def close_cross(op: str, value: int | float) -> dict[str, Any]:
    return close_vs(op, {"value": value})


# ---------------------------------------------------------------- 指标清单


def test_catalog_is_exactly_the_eight_confirmed_indicators() -> None:
    items = condition_catalog()

    assert [item.name for item in items] == [name for name, _ in _CONFIRMED]
    assert [item.title for item in items] == [title for _, title in _CONFIRMED]
    assert all(isinstance(item, ConditionIndicator) for item in items)


def test_catalog_parameters_come_from_the_registry() -> None:
    """参数名、默认值与范围只有注册表一份，清单不另写一份默认值。"""

    by_name = {item.name: item for item in condition_catalog()}

    assert [(param.name, param.default) for param in by_name["rsi"].params] == [("period", 14)]
    assert [(param.name, param.default) for param in by_name["sma"].params] == [("period", 20)]
    assert [(param.name, param.default) for param in by_name["atr"].params] == [("period", 14)]
    assert [(param.name, param.default) for param in by_name["macd"].params] == [
        ("fast", 12),
        ("slow", 26),
        ("signal", 9),
    ]
    assert [(param.name, param.default) for param in by_name["bollinger"].params] == [
        ("period", 20),
        ("num_std", 2.0),
    ]
    assert by_name["close"].params == ()
    assert by_name["volume"].params == ()
    assert by_name["change_24h"].params == ()


def test_catalog_outputs_are_named_and_labelled() -> None:
    """多输出的指标每个输出都能选到，展示名让前端不必自己翻译。"""

    by_name = {item.name: item for item in condition_catalog()}

    assert [(item.name, item.title) for item in by_name["macd"].outputs] == [
        ("macd", "DIF"),
        ("signal", "DEA"),
        ("hist", "柱"),
    ]
    assert [(item.name, item.title) for item in by_name["bollinger"].outputs] == [
        ("upper", "上轨"),
        ("middle", "中轨"),
        ("lower", "下轨"),
    ]
    assert [item.name for item in by_name["rsi"].outputs] == ["rsi"]
    assert all(isinstance(output, ConditionOutput) for output in by_name["macd"].outputs)


def test_catalog_min_bars_matches_the_registry() -> None:
    by_name = {item.name: item for item in condition_catalog()}

    assert by_name["rsi"].min_bars == 15
    assert by_name["macd"].min_bars == 34
    assert by_name["close"].min_bars == 1


# ---------------------------------------------------------------- 穿越边界


def test_cross_above_does_not_count_equality_as_crossing() -> None:
    """恰好相等还不是穿越；从相等变成大于才算穿越。"""

    signals = signal_series(group(close_cross("cross_above", 10)), make_bars([10, 10, 11]))

    assert signals == (False, False, True)


def test_cross_above_fires_only_on_the_first_bar_above() -> None:
    """连续两根都在上方时，只有第一根是穿越。"""

    signals = signal_series(group(close_cross("cross_above", 10)), make_bars([10, 11, 12]))

    assert signals == (False, True, False)


def test_cross_above_cannot_judge_the_first_bar() -> None:
    """首根没有上一根可比，即使已经在常量上方也不算穿越。"""

    signals = signal_series(group(close_cross("cross_above", 10)), make_bars([11, 12]))

    assert signals == (False, False)


def test_cross_below_mirrors_cross_above() -> None:
    signals = signal_series(group(close_cross("cross_below", 10)), make_bars([10, 10, 9, 8]))

    assert signals == (False, False, True, False)


def test_cross_below_from_equality_counts_as_crossing() -> None:
    signals = signal_series(group(close_cross("cross_below", 10)), make_bars([9, 10, 9]))

    assert signals == (False, False, True)


def test_plain_comparison_holds_on_every_bar_it_is_true() -> None:
    signals = signal_series(group(close_cross("lt", 10)), make_bars([9, 10, 9]))

    assert signals == (True, False, True)


# ---------------------------------------------------------------- 不使用未来数据


def test_signals_do_not_depend_on_later_bars() -> None:
    """第 10 根之后暴涨，不改变第 10 根及之前的信号（AC3）。"""

    history = [10, 9, 8, 9, 10, 11, 12, 13, 14, 15]
    conditions = group(close_vs("cross_above", {"indicator": "sma", "output": "sma", "period": 3}))

    without_future = signal_series(conditions, make_bars(history))
    with_future = signal_series(conditions, make_bars([*history, 100, 200, 300]))

    assert with_future[: len(history)] == without_future
    # 用例不是空转：这段历史里确实发生过穿越。
    assert any(without_future)


def test_cross_above_on_moving_average_is_not_changed_by_a_later_spike() -> None:
    """同一件事在「指标对指标」上也成立：后面暴涨不会让前面凭空出现穿越。"""

    history = [10, 11, 12, 11, 10, 11, 12]
    conditions = group(
        close_vs("cross_above", {"indicator": "sma", "output": "sma", "period": 3}),
        close_vs("gt", {"indicator": "change_24h", "output": "change_24h"}),
    )

    without_future = signal_series(conditions, make_bars(history, bar="1d"))
    with_future = signal_series(conditions, make_bars([*history, 500], bar="1d"))

    assert with_future[: len(history)] == without_future


def test_undefined_indicator_values_never_raise_a_signal() -> None:
    """热身区间里指标值是 None，条件一律不成立，而不是当成 0 去比较。"""

    signals = signal_series(
        group(
            {
                "left": {"indicator": "rsi", "output": "rsi", "period": 14},
                "op": "lt",
                "right": {"value": 100},
            }
        ),
        make_bars([10, 11, 12]),
    )

    assert signals == (False, False, False)


# ---------------------------------------------------------------- 组合与多输出


def test_and_requires_every_condition() -> None:
    conditions = group(close_cross("gt", 10), close_cross("lt", 12))

    assert signal_series(conditions, make_bars([9, 10, 11, 12])) == (False, False, True, False)


def test_or_accepts_any_condition() -> None:
    conditions = group(close_cross("gt", 10), close_cross("lt", 9), logic="or")

    assert signal_series(conditions, make_bars([8, 10, 11])) == (True, False, True)


def test_multi_output_operand_reads_the_selected_column() -> None:
    """MACD 的三个输出各自可取：加速上涨里 DIF 与柱状差都为正。"""

    bars = make_bars([index * index for index in range(1, 41)])
    hist = signal_series(
        group(
            {
                "left": {"indicator": "macd", "output": "hist"},
                "op": "gt",
                "right": {"value": 0},
            }
        ),
        bars,
    )
    dif = signal_series(
        group(
            {
                "left": {"indicator": "macd", "output": "macd"},
                "op": "gt",
                "right": {"value": 0},
            }
        ),
        bars,
    )

    assert hist[-1] is True
    assert dif[-1] is True


def test_change_24h_operand_uses_one_day_of_bars() -> None:
    """小时线上「24 小时涨跌幅 > 0」要到第 24 根才可能成立。"""

    conditions = group(
        {
            "left": {"indicator": "change_24h", "output": "change_24h"},
            "op": "gt",
            "right": {"value": 0},
        }
    )

    signals = signal_series(conditions, make_bars(range(1, 27), bar="1h"))

    assert signals[:24] == (False,) * 24
    assert signals[24] is True


def test_normalized_rule_group_can_be_evaluated() -> None:
    """落库前规范化的条件组直接可求值：中间的参数补全不会改变求值入口。"""

    rule, _ = normalize_rule(
        {
            "entry": {
                "logic": "and",
                "conditions": [
                    {
                        "left": {"indicator": "RSI", "period": 2},
                        "op": "lt",
                        "right": {"value": 100},
                    }
                ],
            },
            "exit": {
                "logic": "or",
                "conditions": [{"left": {"indicator": "close"}, "op": "gt", "right": {"value": 0}}],
                "take_profit_pct": 10,
            },
        },
        timeframe="1d",
        direction="long_only",
    )

    assert rule["entry"]["conditions"][0]["left"]["indicator"] == "rsi"
    assert signal_series(rule["entry"], make_bars([1, 2, 1, 2], bar="1d")) == (
        False,
        False,
        True,
        True,
    )


@pytest.mark.parametrize("count", [1, 2])
def test_series_shorter_than_the_warmup_is_all_false(count: int) -> None:
    signals = signal_series(
        group(
            {
                "left": {"indicator": "bollinger", "output": "upper"},
                "op": "gt",
                "right": {"indicator": "bollinger", "output": "lower"},
            }
        ),
        make_bars(range(1, count + 1)),
    )

    assert signals == (False,) * count

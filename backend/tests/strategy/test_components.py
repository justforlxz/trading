"""六个基础组件：纯度、读数口径、登记与错误路径。

组件是纯函数式的：`evaluate` 只读视图、不取数、不看时钟。纯度不是靠约定，而是靠
`CountingView` 计数：任何 IO 语义的属性被访问都记一次并立刻失败，正常路径下断言
计数为 0。

数值用例都是「已知答案」：手算的均线偏离、收益率、涨跌家数直接写成断言，不用被测
实现生成期望值。
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core import Bar, InvariantViolation, Timeframe, ValidationError
from app.market import Matrix
from app.strategy import (
    Breadth,
    Component,
    ComponentSignal,
    CorrelationShift,
    MarketView,
    MeanReversion,
    Momentum,
    RelativeStrength,
    Trend,
    get_component,
    list_components,
    register_component,
)

BAR = "1d"
START = datetime(2026, 1, 1, tzinfo=UTC)
TEN_PLACES = Decimal("1e-10")

# 视图允许被读的成员：组件的全部输入只能来自这里。
READ_MEMBERS = frozenset({"as_of", "product_keys", "bars", "indicators", "matrix", "candles"})
# IO 语义的成员：组件一旦碰它们就说明它在自己取数，而不是读快照。
IO_MEMBERS = frozenset(
    {"session", "session_scope", "connect", "execute", "query", "fetch", "client", "get_engine"}
)


def make_bars(closes: list[int], *, inst_id: str = "AAPL") -> list[Bar]:
    """按收盘价造一段连续的日线；高、低、量取固定值。"""

    timeframe = Timeframe.parse(BAR)
    return [
        Bar(
            inst_id=inst_id,
            timeframe=timeframe,
            open_time=START + index * timedelta(seconds=timeframe.seconds),
            open=Decimal(close),
            high=Decimal(close) + 1,
            low=Decimal(close) - 1,
            close=Decimal(close),
            volume=Decimal(1000),
            confirm=True,
            source="okx_spot",
        )
        for index, close in enumerate(closes)
    ]


def make_matrix(symbols: tuple[str, ...], *, coefficient: float = 0.6) -> Matrix:
    """对角为 1、交叉取固定系数的关系矩阵。"""

    return Matrix(
        symbols=symbols,
        bar=BAR,
        window=20,
        as_of=START,
        coefficients={
            left: {right: (1.0 if left == right else coefficient) for right in symbols}
            for left in symbols
        },
        samples={},
    )


def make_view(candles: dict[str, list[Bar]]) -> MarketView:
    """按「产品键 → K 线」造视图，矩阵覆盖同一组产品键。"""

    return MarketView(
        as_of=START,
        candles={key: {BAR: bars} for key, bars in candles.items()},
        matrix=make_matrix(tuple(candles)),
    )


def ramp_universe(products: int = 12, steps: int = 120) -> dict[str, list[Bar]]:
    """一组有涨有跌、序列各不相同的产品：宽度类组件才有东西可算。"""

    return {
        f"P{index}": make_bars(
            [100 + 7 * index + ((step * (index + 2)) % 23) - 11 for step in range(steps)],
            inst_id=f"P{index}-USDT",
        )
        for index in range(products)
    }


class CountingView:
    """把真视图包一层，记录读次数。

    普通读（`bars` / `matrix` / `as_of` …）记到 `reads`；IO 语义的成员记到 `io_calls`
    并立刻失败——组件本该拿不到它，能拿到就说明输入不止一个来源。
    """

    def __init__(self, view: MarketView) -> None:
        object.__setattr__(self, "_view", view)
        object.__setattr__(self, "reads", 0)
        object.__setattr__(self, "io_calls", 0)

    def __getattr__(self, name: str) -> object:
        if name in IO_MEMBERS:
            object.__setattr__(self, "io_calls", self.io_calls + 1)
            raise AssertionError(f"组件访问了非视图成员:{name}")
        target = getattr(self._view, name)
        if name not in READ_MEMBERS:
            object.__setattr__(self, "io_calls", self.io_calls + 1)
        object.__setattr__(self, "reads", self.reads + 1)
        return target


# ------------------------------------------------------------------ 协议与登记


def test_component_protocol_takes_only_the_view() -> None:
    assert list(inspect.signature(Component.evaluate).parameters) == ["self", "view"]
    assert inspect.signature(Component.evaluate).return_annotation in (
        ComponentSignal,
        "ComponentSignal",
    )


def test_registry_lists_the_six_components() -> None:
    assert list_components() == [
        "breadth",
        "correlation_shift",
        "mean_reversion",
        "momentum",
        "relative_strength",
        "trend",
    ]
    assert get_component("trend") is Trend


def test_unknown_component_name_is_rejected() -> None:
    with pytest.raises(ValidationError) as raised:
        get_component("no_such_component")

    assert "no_such_component" in str(raised.value)


def test_duplicate_component_registration_is_rejected() -> None:
    class Duplicate:
        name = "trend"

        def evaluate(self, view: MarketView) -> ComponentSignal:  # pragma: no cover - 不会被调用
            raise AssertionError

    with pytest.raises(InvariantViolation) as raised:
        register_component(Duplicate)  # type: ignore[arg-type]

    assert "trend" in str(raised.value)


def test_component_without_a_name_is_rejected() -> None:
    class Nameless:
        def evaluate(self, view: MarketView) -> ComponentSignal:  # pragma: no cover - 不会被调用
            raise AssertionError

    with pytest.raises(InvariantViolation):
        register_component(Nameless)  # type: ignore[arg-type]


# --------------------------------------------------------------- 组件信号的校验


def test_component_signal_freezes_scores() -> None:
    source = {"AAPL": Decimal("0.5")}
    signal = ComponentSignal(name="trend", as_of=START, scores=source)

    source["AAPL"] = Decimal("-0.5")

    assert signal.scores["AAPL"] == Decimal("0.5")
    with pytest.raises(TypeError):
        signal.scores["AAPL"] = Decimal(0)  # type: ignore[index]


@pytest.mark.parametrize(
    ("signal", "field"),
    [
        ({"name": "", "scores": {}}, "组件名"),
        ({"name": "trend", "as_of": datetime(2026, 1, 1), "scores": {}}, "as_of"),
        ({"name": "trend", "scores": {"": Decimal(0)}}, "product_key"),
        ({"name": "trend", "scores": {"AAPL": 0.5}}, "Decimal"),
        ({"name": "trend", "scores": {"AAPL": Decimal("1.5")}}, "越界"),
        ({"name": "trend", "scores": {"AAPL": Decimal("NaN")}}, "越界"),
    ],
)
def test_component_signal_rejects_invalid_input(signal: dict[str, object], field: str) -> None:
    payload: dict[str, object] = {"name": "trend", "as_of": START, "scores": {}}
    payload.update(signal)

    with pytest.raises(ValidationError) as raised:
        ComponentSignal(**payload)  # type: ignore[arg-type]

    assert field in str(raised.value)


# ------------------------------------------------------------------------ 纯度


@pytest.mark.parametrize(
    "component",
    [
        Trend(),
        Momentum(),
        MeanReversion(),
        RelativeStrength(),
        Breadth(),
        CorrelationShift(),
    ],
    ids=lambda item: item.name,
)
def test_component_reads_only_the_view(component: Component) -> None:
    spy = CountingView(make_view(ramp_universe()))

    signal = component.evaluate(spy)  # type: ignore[arg-type]

    assert signal.name == component.name
    assert signal.as_of == START
    assert spy.io_calls == 0
    assert spy.reads > 0


@pytest.mark.parametrize(
    "component",
    [
        Trend(),
        Momentum(),
        MeanReversion(),
        RelativeStrength(),
        Breadth(),
        CorrelationShift(),
    ],
    ids=lambda item: item.name,
)
def test_component_is_deterministic(component: Component) -> None:
    view = make_view(ramp_universe())

    assert component.evaluate(view) == component.evaluate(view)


@pytest.mark.parametrize(
    "component",
    [
        Trend(),
        Momentum(),
        MeanReversion(),
        RelativeStrength(),
        Breadth(),
        CorrelationShift(),
    ],
    ids=lambda item: item.name,
)
def test_component_returns_nothing_for_an_empty_view(component: Component) -> None:
    assert component.evaluate(make_view({})).scores == {}


# ------------------------------------------------------------- 趋势跟踪（已知答案）


def test_trend_scores_the_gap_to_its_own_average() -> None:
    # 最近 3 根均值 = (3+4+5)/3 = 4，收盘 5，偏离 25% → 0.25 / 1.25 = 0.2
    view = make_view({"AAPL": make_bars([1, 2, 3, 4, 5])})

    signal = Trend(window=3).evaluate(view)

    assert signal.scores == {"AAPL": Decimal("0.2")}


def test_trend_skips_products_without_enough_bars() -> None:
    view = make_view({"AAPL": make_bars([1, 2, 3])})

    assert Trend(window=10).evaluate(view).scores == {}


def test_trend_rejects_a_non_positive_window() -> None:
    with pytest.raises(ValidationError) as raised:
        Trend(window=0)

    assert "窗口" in str(raised.value)


# ------------------------------------------------------------------ 动量（已知答案）


def test_momentum_scores_the_window_return() -> None:
    # 5 / 1 - 1 = 4；4 / (1 + 4) = 0.8
    view = make_view({"AAPL": make_bars([1, 2, 3, 4, 5])})

    assert Momentum(window=4).evaluate(view).scores == {"AAPL": Decimal("0.8")}


def test_momentum_skips_products_without_enough_bars() -> None:
    view = make_view({"AAPL": make_bars([1, 2, 3])})

    assert Momentum(window=5).evaluate(view).scores == {}


# -------------------------------------------------------------- 均值回归（已知答案）


def test_mean_reversion_is_the_opposite_sign_of_trend() -> None:
    view = make_view({"AAPL": make_bars([1, 2, 3, 4, 5])})

    assert MeanReversion(window=3).evaluate(view).scores == {"AAPL": Decimal("-0.2")}


def test_mean_reversion_rewards_the_cheap_side() -> None:
    view = make_view({"AAPL": make_bars([5, 4, 3, 2, 1])})

    assert MeanReversion(window=3).evaluate(view).scores["AAPL"] > Decimal(0)


# -------------------------------------------------------------- 相对强弱（已知答案）


def test_relative_strength_subtracts_the_group_median() -> None:
    # 两标的收益率 10% 与 20%，中位数 15% → 偏离 ±5%，压到 ±0.05/1.05
    view = make_view({"AAPL": make_bars([100, 110]), "MSFT": make_bars([100, 120])})

    scores = RelativeStrength(window=1).evaluate(view).scores

    assert scores["AAPL"] < Decimal(0) < scores["MSFT"]
    assert abs(abs(scores["AAPL"]) - abs(scores["MSFT"])) <= TEN_PLACES


def test_relative_strength_is_zero_when_everyone_moves_together() -> None:
    view = make_view({"AAPL": make_bars([100, 110]), "MSFT": make_bars([200, 220])})

    assert RelativeStrength(window=1).evaluate(view).scores == {
        "AAPL": Decimal(0),
        "MSFT": Decimal(0),
    }


def test_relative_strength_returns_nothing_without_returns() -> None:
    view = make_view({"AAPL": make_bars([100]), "MSFT": make_bars([200])})

    assert RelativeStrength(window=1).evaluate(view).scores == {}


# ------------------------------------------------------------------ 广度（已知答案）


def test_breadth_gives_every_product_the_same_group_score() -> None:
    # 两涨一跌 → (2 - 1) / 3
    view = make_view(
        {
            "AAPL": make_bars([100, 101]),
            "MSFT": make_bars([100, 102]),
            "NVDA": make_bars([100, 99]),
        }
    )

    signal = Breadth().evaluate(view)

    assert set(signal.scores) == {"AAPL", "MSFT", "NVDA"}
    assert set(signal.scores.values()) == {Decimal(1) / Decimal(3)}


def test_breadth_returns_nothing_when_nobody_has_two_bars() -> None:
    view = make_view({"AAPL": make_bars([100]), "MSFT": make_bars([200])})

    assert Breadth().evaluate(view).scores == {}


def test_breadth_skips_products_without_two_bars() -> None:
    """不足两根 K 线的产品没有方向，不该跟着整组拿到一个读数。"""

    view = make_view(
        {
            "AAPL": make_bars([100, 101]),
            "MSFT": make_bars([100, 99]),
            "NVDA": make_bars([100]),
        }
    )

    scores = Breadth().evaluate(view).scores

    assert set(scores) == {"AAPL", "MSFT"}
    assert set(scores.values()) == {Decimal(0)}


# ------------------------------------------------------------ 相关性变化（已知答案）


def _closes_from_returns(returns: list[int], *, start: int = 100) -> list[int]:
    """按百分比整数序列复利出收盘价，便于手工构造收益率。"""

    values = [start]
    for percent in returns:
        values.append(values[-1] * (100 + percent) // 100)
    return values


def test_correlation_shift_is_zero_when_tracking_the_group_never_changes() -> None:
    """另一侧的收益率恒为 0 时，整组收益就是本标的的一半，相关系数恒为 1，变化为 0。"""

    view = make_view(
        {
            "AAPL": make_bars(_closes_from_returns([2, -1, 3, -2, 4, -3, 2, -1, 3, -2])),
            "MSFT": make_bars([100] * 11),
        }
    )

    score = CorrelationShift(window=4).evaluate(view).scores["AAPL"]

    assert abs(score) <= TEN_PLACES


def test_correlation_shift_skips_products_without_two_windows() -> None:
    view = make_view({"AAPL": make_bars([100, 101, 102]), "MSFT": make_bars([100, 102, 103])})

    assert CorrelationShift(window=20).evaluate(view).scores == {}


def test_correlation_shift_skips_products_whose_returns_never_vary() -> None:
    view = make_view(
        {
            "AAPL": make_bars([100] * 20),
            "MSFT": make_bars(_closes_from_returns([1, -1, 2, -2, 1, -1, 2, -2, 1, -1])),
            "NVDA": make_bars(_closes_from_returns([-1, 1, -2, 2, -1, 1, -2, 2, -1, 1])),
        }
    )

    assert "AAPL" not in CorrelationShift(window=4).evaluate(view).scores


def test_correlation_shift_uses_the_shared_tail_when_histories_differ() -> None:
    """历史长度不同时按共同时刻比较。

    各自切到「最后 2 * window + 1 根」再取交集会落空（两段窗口落在不同时间段），
    因此实现先求共同时刻、再只对这些时刻求收益率。
    """

    long_returns = [2, -1, 3, -2, 4, -3, 2, -1, 3, -2, 1, -1] * 3
    short_returns = [-1, 3, -2, 4, -3, 2, -1, 3, -2, 1, -1, 2, -1, 3, -2, 4, -3, 2, -1, 3]
    view = make_view(
        {
            "AAPL": make_bars(_closes_from_returns(long_returns)),
            "MSFT": make_bars(_closes_from_returns(short_returns)),
        }
    )

    scores = CorrelationShift(window=5).evaluate(view).scores

    assert set(scores) == {"AAPL", "MSFT"}


def test_correlation_shift_rejects_a_window_below_three() -> None:
    with pytest.raises(ValidationError) as raised:
        CorrelationShift(window=2)

    assert "窗口" in str(raised.value)

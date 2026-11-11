"""两类组合模板：golden 用例、形态断言、配权口径与登记隔离。

golden 用例的输入是固定的人工数据（12 个标的、120 根日线），期望值由规范里的公式
独立推导后写死在这里，不由被测实现生成；比对容差 1e-9。

形态断言把两类模板「固住」：方向性模板只出一个方向（golden 这一份是全多头，不含
空头腿），相对价值模板必须多空并存。
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core import Bar, InvariantViolation, Timeframe, ValidationError
from app.indicators import Param
from app.market import Matrix
from app.strategy import (
    BollingerReversion,
    Breadth,
    CorrelationShift,
    Directional,
    MacdMomentum,
    MaCross,
    MarketView,
    RelativeValue,
    RsiReversal,
    Strategy,
    StrategyInstanceRow,
    StrategyMeta,
    StrategyTemplateRow,
    TargetPortfolio,
    Template,
    Trend,
    get_strategy,
    get_template,
    list_templates,
    register_template,
)
from app.strategy.templates.directional import side_of

BAR = "1d"
START = datetime(2026, 1, 1, tzinfo=UTC)
TOLERANCE = Decimal("1e-9")
# 两腿在该对预算里的占比下限（正文「两腿权重接近但不必相等」的具体口径）。
LEG_SHARE_FLOOR = Decimal("0.4")

TICKERS = (
    "AAPL",
    "AMD",
    "AMZN",
    "AVGO",
    "GOOGL",
    "META",
    "MSFT",
    "NFLX",
    "NVDA",
    "ORCL",
    "PLTR",
    "TSLA",
)

# 12 个标的 × 120 根日线：整数收盘价，无随机、无外部数据。
STEPS = 120


def closes(index: int) -> list[int]:
    base = 100 + 7 * index
    return [base + ((step * (index + 2)) % 23) - 11 for step in range(STEPS)]


def make_bars(values: list[int], *, inst_id: str) -> list[Bar]:
    timeframe = Timeframe.parse(BAR)
    return [
        Bar(
            inst_id=inst_id,
            timeframe=timeframe,
            open_time=START + index * timedelta(seconds=timeframe.seconds),
            open=Decimal(value),
            high=Decimal(value) + 1,
            low=Decimal(value) - 1,
            close=Decimal(value),
            volume=Decimal(1000),
            confirm=True,
            source="okx_spot",
        )
        for index, value in enumerate(values)
    ]


def make_matrix(keys: tuple[str, ...], *, coefficient: float = 0.6) -> Matrix:
    return Matrix(
        symbols=keys,
        bar=BAR,
        window=20,
        as_of=START,
        coefficients={
            left: {right: (1.0 if left == right else coefficient) for right in keys}
            for left in keys
        },
        samples={},
    )


def make_view(
    candles: dict[str, list[Bar]] | None = None, *, coefficient: float = 0.6
) -> MarketView:
    if candles is None:
        candles = {
            ticker: make_bars(closes(index), inst_id=f"{ticker}-USDT")
            for index, ticker in enumerate(TICKERS)
        }
    return MarketView(
        as_of=START,
        candles={key: {BAR: bars} for key, bars in candles.items()},
        matrix=make_matrix(tuple(candles), coefficient=coefficient),
    )


# 独立推导的期望腿：(product_key, side, target_weight)
GOLDEN_DIRECTIONAL = (
    ("AVGO", "long", Decimal("0.3198220180652744847091206444")),
    ("NVDA", "long", Decimal("0.3099108227065708030657558613")),
    ("ORCL", "long", Decimal("0.3702671592281547122251234943")),
)

GOLDEN_RELATIVE_VALUE = (
    ("AVGO", "short", Decimal("0.2389406912999552824657579623")),
    ("GOOGL", "long", Decimal("0.2610593087000447175342420377")),
    ("ORCL", "short", Decimal("0.2692463013674402426550566402")),
    ("PLTR", "long", Decimal("0.2307536986325597573449433598")),
)


def _legs(portfolio: TargetPortfolio) -> tuple[tuple[str, str, Decimal], ...]:
    return tuple((leg.product_key, leg.side, leg.target_weight) for leg in portfolio.legs)


def _assert_close(actual: Decimal, expected: Decimal) -> None:
    assert abs(actual - expected) <= TOLERANCE, f"{actual} != {expected}"


# ------------------------------------------------------------------ 方向性模板


def test_directional_matches_the_golden_legs() -> None:
    portfolio = Directional(leg_count=3).build(make_view())

    assert [leg[0] for leg in _legs(portfolio)] == [leg[0] for leg in GOLDEN_DIRECTIONAL]
    assert [leg[1] for leg in _legs(portfolio)] == [leg[1] for leg in GOLDEN_DIRECTIONAL]
    for actual, expected in zip(_legs(portfolio), GOLDEN_DIRECTIONAL, strict=True):
        _assert_close(actual[2], expected[2])


def test_directional_golden_case_has_no_short_leg() -> None:
    portfolio = Directional(leg_count=3).build(make_view())

    assert portfolio.legs
    assert {leg.side for leg in portfolio.legs} == {"long"}


def test_directional_never_mixes_directions() -> None:
    """全多头或全空头：镜像行情下方向翻转，但仍然只有一个方向。"""

    mirrored = {
        ticker: make_bars([1000 - value for value in closes(index)], inst_id=f"{ticker}-USDT")
        for index, ticker in enumerate(TICKERS)
    }

    portfolio = Directional(leg_count=3).build(make_view(mirrored))

    assert portfolio.legs
    assert len({leg.side for leg in portfolio.legs}) == 1
    assert {leg.side for leg in portfolio.legs} == {"short"}


def test_directional_weights_absolute_values_sum_to_one() -> None:
    portfolio = Directional(leg_count=4).build(make_view())

    assert abs(sum((leg.target_weight for leg in portfolio.legs), Decimal(0)) - Decimal(1)) <= (
        TOLERANCE
    )


@pytest.mark.parametrize(
    ("market", "trends", "expected"),
    [
        (Decimal("0.3333333333333333333333333333"), [Decimal("0.10"), Decimal("0.05")], "long"),
        (Decimal("-0.3333333333333333333333333333"), [Decimal("-0.10")], "short"),
        (Decimal(0), [Decimal("0.10"), Decimal("-0.10")], None),
        (Decimal("0.05"), [Decimal("-0.05")], None),
    ],
    ids=["breadth-and-trend-agree", "both-fall", "cancel-at-zero", "small-values-cancel"],
)
def test_side_of_reports_no_direction_when_the_two_sources_cancel(
    market: Decimal, trends: list[Decimal], expected: str | None
) -> None:
    """抵消到正好 0 就是没有方向；差一个最小单位也要给方向。"""

    assert side_of(market, trends) == expected


def test_directional_builds_nothing_when_breadth_and_trend_cancel() -> None:
    """广度与平均趋势正好抵消到 0：方向未定，不建仓。

    构造：前 100 根有涨跌（相关性变化因而有读数），最后 20 根横在各自的价位上。
    于是最后一根与上一根相同（广度为 0）、收盘价又正好等于 20 根均线（趋势为 0），
    两个 0 取平均仍然是 0。
    """

    undetermined = {}
    for index, ticker in enumerate(TICKERS):
        earlier = closes(index)[:100]
        tail = earlier[-1] + 3 + index
        undetermined[ticker] = make_bars(earlier + [tail] * 20, inst_id=f"{ticker}-USDT")

    view = make_view(undetermined)
    # 先确认这份输入真的走到了「方向未定」这一步：三个组件都有读数。
    assert Trend().evaluate(view).scores
    assert set(Breadth().evaluate(view).scores.values()) == {Decimal(0)}
    assert CorrelationShift().evaluate(view).scores

    assert Directional().build(view).legs == ()


def test_directional_builds_nothing_without_enough_history() -> None:
    short = {
        ticker: make_bars(closes(index)[-5:], inst_id=f"{ticker}-USDT")
        for index, ticker in enumerate(TICKERS)
    }

    assert Directional().build(make_view(short)).legs == ()


# ---------------------------------------------------------------- 相对价值模板


def test_relative_value_matches_the_golden_legs() -> None:
    portfolio = RelativeValue(pair_count=2).build(make_view())

    assert [leg[0] for leg in _legs(portfolio)] == [leg[0] for leg in GOLDEN_RELATIVE_VALUE]
    assert [leg[1] for leg in _legs(portfolio)] == [leg[1] for leg in GOLDEN_RELATIVE_VALUE]
    for actual, expected in zip(_legs(portfolio), GOLDEN_RELATIVE_VALUE, strict=True):
        _assert_close(actual[2], expected[2])


def test_relative_value_always_carries_both_directions() -> None:
    portfolio = RelativeValue(pair_count=2).build(make_view())

    assert portfolio.legs
    assert {leg.side for leg in portfolio.legs} == {"long", "short"}


def test_relative_value_weights_absolute_values_sum_to_one() -> None:
    for pair_count in (1, 2, 3):
        portfolio = RelativeValue(pair_count=pair_count).build(make_view())
        total = sum((leg.target_weight for leg in portfolio.legs), Decimal(0))

        assert abs(total - Decimal(1)) <= TOLERANCE


def test_relative_value_uses_each_product_at_most_once() -> None:
    portfolio = RelativeValue(pair_count=6).build(make_view())

    keys = [leg.product_key for leg in portfolio.legs]
    assert len(keys) == len(set(keys))


def test_relative_value_ignores_pairs_below_the_correlation_floor() -> None:
    portfolio = RelativeValue(pair_count=2).build(make_view(coefficient=0.1))

    assert portfolio.legs == ()


def test_relative_value_builds_nothing_with_a_single_product() -> None:
    view = make_view(
        {"AAPL": make_bars(closes(0), inst_id="AAPL-USDT")},
    )

    assert RelativeValue().build(view).legs == ()


def test_relative_value_keeps_both_legs_in_the_same_size_range() -> None:
    """偏离再悬殊，两腿也要同量级：不能退化成单边持仓，也不能出现零权重腿。"""

    # 一个标的恰好横盘（偏离 0），另一个远低于自己的 20 根均线（偏离很大）。
    lop_sided = {
        "AAPL": make_bars([100] * 25, inst_id="AAPL-USDT"),
        "MSFT": make_bars([200] * 24 + [100], inst_id="MSFT-USDT"),
    }

    portfolio = RelativeValue().build(make_view(lop_sided))

    assert {leg.side for leg in portfolio.legs} == {"long", "short"}
    for leg in portfolio.legs:
        assert leg.target_weight >= LEG_SHARE_FLOOR - TOLERANCE
        assert leg.target_weight <= Decimal(1) - LEG_SHARE_FLOOR + TOLERANCE


# ------------------------------------------------------------------- 重复调用


@pytest.mark.parametrize(
    "template",
    [Directional(leg_count=3), RelativeValue(pair_count=2)],
    ids=lambda item: item.meta.name,
)
def test_templates_are_deterministic(template: Template) -> None:
    view = make_view()

    assert template.build(view) == template.build(view)


# ---------------------------------------------------------------- 登记与隔离


def test_template_protocol_takes_only_the_view() -> None:
    assert list(inspect.signature(Template.build).parameters) == ["self", "view"]
    assert inspect.signature(Template.build).return_annotation in (
        TargetPortfolio,
        "TargetPortfolio",
    )


def test_registry_lists_only_the_two_templates() -> None:
    assert list_templates() == ["directional", "relative_value"]
    assert get_template("directional") is Directional
    assert get_template("relative_value") is RelativeValue


def test_unknown_template_name_is_rejected() -> None:
    with pytest.raises(ValidationError) as raised:
        get_template("no_such_template")

    assert "no_such_template" in str(raised.value)


def test_duplicate_template_registration_is_rejected() -> None:
    class Duplicate:
        meta = Directional.meta
        param_schema: tuple[()] = ()

        def build(self, view: MarketView) -> TargetPortfolio:  # pragma: no cover - 不会被调用
            raise AssertionError

    with pytest.raises(InvariantViolation) as raised:
        register_template(Duplicate)  # type: ignore[arg-type]

    assert "directional" in str(raised.value)


def test_template_with_a_bad_default_parameter_is_rejected() -> None:
    class BadDefault:
        meta = Directional.meta
        param_schema = (Param("leg_count", "腿数", "int", 0, 1, 10),)

        def build(self, view: MarketView) -> TargetPortfolio:  # pragma: no cover - 不会被调用
            raise AssertionError

    with pytest.raises(ValidationError):
        register_template(BadDefault)  # type: ignore[arg-type]


# ------------------------------------------------------- 旧策略是组件的用例


@pytest.mark.parametrize(
    "strategy",
    [MaCross, MacdMomentum, RsiReversal, BollingerReversion],
    ids=lambda item: item.meta.name,
)
def test_legacy_strategies_are_component_use_cases(strategy: type[Strategy]) -> None:
    """四个经典策略仍可按名字取到、能产出目标组合，但不在模板表里。"""

    instance = strategy()
    portfolio = instance.evaluate(make_view())

    assert portfolio.legs
    assert abs(sum((leg.target_weight for leg in portfolio.legs), Decimal(0)) - Decimal(1)) <= (
        TOLERANCE
    )
    assert strategy.meta.name not in list_templates()
    assert get_strategy(strategy.meta.name) is strategy


def test_legacy_strategy_shape_is_equal_weight() -> None:
    portfolio = MaCross().evaluate(make_view())
    weights = {leg.target_weight for leg in portfolio.legs}

    assert len(weights) == 1
    assert abs(weights.pop() * len(portfolio.legs) - Decimal(1)) <= TOLERANCE


def test_strategy_meta_requires_a_version() -> None:
    """版本是复现的依据，空版本等于没有版本。"""

    assert Directional.meta.version == "1.0.0"
    with pytest.raises(ValidationError) as raised:
        StrategyMeta(name="directional", title="方向性组合", version="  ")

    assert "version" in str(raised.value)


def test_template_and_instance_rows_carry_the_strategy_version() -> None:
    """对外契约里的 `strategy_version` 必须有数据来源：模板存当前版本，实例存建时版本。"""

    template_columns = StrategyTemplateRow.__table__.columns
    instance_columns = StrategyInstanceRow.__table__.columns

    assert "version" in template_columns
    assert "strategy_version" in instance_columns

    references = instance_columns["strategy_id"].foreign_keys
    assert {reference.target_fullname for reference in references} == {
        "strategy_templates.strategy_id"
    }

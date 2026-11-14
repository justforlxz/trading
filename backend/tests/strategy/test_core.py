"""策略核心：目标组合、只读行情视图、策略协议、注册表与参数校验。

纯值对象与纯计算，不连网络、不建库；`MarketView` 手工构造，K 线与关系矩阵都来自
本文件里的工厂函数。每个用例同时覆盖正常路径与错误路径。
"""

from __future__ import annotations

import ast
import inspect
import re
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.core import Bar, InvariantViolation, Timeframe, ValidationError
from app.indicators import Param, compute
from app.market import Matrix
from app.strategy import (
    MarketView,
    Requirements,
    Strategy,
    StrategyMeta,
    TargetLeg,
    TargetPortfolio,
    get_strategy,
    list_strategies,
    register_strategy,
    resolve_params,
)

BAR = "1h"
START = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
STRATEGY_DIR = Path(__file__).resolve().parents[2] / "app" / "strategy"


def make_bars(closes: list[int], *, inst_id: str = "XAAPL-USDT", bar: str = BAR) -> list[Bar]:
    """按收盘价造一段连续 K 线；未指定的高、低、量取固定值。"""

    timeframe = Timeframe.parse(bar)
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


def make_matrix(symbols: tuple[str, ...], *, as_of: datetime = START) -> Matrix:
    """按给定标的手工拼一张对角为 1、交叉为 0 的关系矩阵。"""

    coefficients = {
        left: {right: (1.0 if left == right else 0.0) for right in symbols} for left in symbols
    }
    return Matrix(
        symbols=symbols,
        bar=BAR,
        window=20,
        as_of=as_of,
        coefficients=coefficients,
        samples={},
    )


def make_view(
    candles: dict[str, dict[str, list[Bar]]] | None = None,
    *,
    as_of: datetime = START,
) -> MarketView:
    """构造只读视图；默认覆盖两个产品、各 5 根 K 线。"""

    if candles is None:
        candles = {
            "XAAPL": {BAR: make_bars([1, 2, 3, 4, 5], inst_id="XAAPL-USDT")},
            "XMSFT": {BAR: make_bars([10, 20, 30, 40, 50], inst_id="XMSFT-USDT")},
        }
    return MarketView(as_of=as_of, candles=candles, matrix=make_matrix(tuple(candles), as_of=as_of))


@register_strategy
class ExampleStrategy:
    """示例策略：每个产品按收盘价方向的等权腿，用来验证协议与注册表。"""

    meta = StrategyMeta(name="example_follow_close", title="示例收盘方向", summary="测试用")
    param_schema = (Param("lookback", "回看根数", "int", 2, 1, 10),)
    requires = Requirements(bar=BAR, lookback=2)

    def evaluate(self, view: MarketView) -> TargetPortfolio:
        legs: list[TargetLeg] = []
        for product_key, bars in view.bars(view.product_keys, BAR).items():
            side = "long" if bars[-1].close >= bars[0].close else "short"
            legs.append(
                TargetLeg(
                    product_key=product_key,
                    side=side,
                    target_weight=Decimal("0.25"),
                    reason="收盘价方向",
                )
            )
        return TargetPortfolio(as_of=view.as_of, legs=tuple(legs))


# ------------------------------------------------------------ 目标组合：值对象


def test_net_exposure_is_long_weight_minus_short_weight() -> None:
    """四腿 +0.4 / +0.3 / −0.2 / −0.5 手算等于 0。"""

    legs = (
        TargetLeg("A", "long", Decimal("0.4"), "强于同类"),
        TargetLeg("B", "long", Decimal("0.3"), "趋势向上"),
        TargetLeg("C", "short", Decimal("0.2"), "相对走弱"),
        TargetLeg("D", "short", Decimal("0.5"), "相关性反转"),
    )
    portfolio = TargetPortfolio(as_of=START, legs=legs)

    assert abs(portfolio.net_exposure - Decimal("0.0")) <= Decimal("1e-9")
    assert portfolio.legs == legs
    assert portfolio.as_of == START


def test_target_portfolio_allows_no_legs() -> None:
    portfolio = TargetPortfolio(as_of=START, legs=())

    assert portfolio.legs == ()
    assert portfolio.net_exposure == Decimal(0)


def test_target_leg_is_frozen() -> None:
    leg = TargetLeg("A", "long", Decimal("0.1"))

    with pytest.raises(FrozenInstanceError):
        leg.side = "short"  # type: ignore[misc]


def test_target_portfolio_is_frozen() -> None:
    portfolio = TargetPortfolio(as_of=START, legs=())

    with pytest.raises(FrozenInstanceError):
        portfolio.as_of = START  # type: ignore[misc]


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"product_key": ""}, "product_key"),
        ({"side": "flat"}, "side"),
        ({"target_weight": 0.5}, "target_weight"),
        ({"target_weight": Decimal("-0.1")}, "target_weight"),
    ],
)
def test_target_leg_rejects_invalid_fields(kwargs: dict[str, object], field: str) -> None:
    defaults: dict[str, object] = {"product_key": "A", "side": "long", "target_weight": Decimal(0)}
    defaults.update(kwargs)

    with pytest.raises(ValidationError) as raised:
        TargetLeg(**defaults)  # type: ignore[arg-type]

    assert field in str(raised.value)


def test_target_portfolio_rejects_naive_as_of() -> None:
    with pytest.raises(ValidationError) as raised:
        TargetPortfolio(as_of=datetime(2026, 11, 6), legs=())

    assert "as_of" in str(raised.value)


def test_target_portfolio_rejects_duplicate_product_key() -> None:
    legs = (
        TargetLeg("A", "long", Decimal("0.2")),
        TargetLeg("A", "short", Decimal("0.1")),
    )

    with pytest.raises(ValidationError) as raised:
        TargetPortfolio(as_of=START, legs=legs)

    assert "A" in str(raised.value)


def test_target_portfolio_rejects_non_leg_items() -> None:
    with pytest.raises(ValidationError) as raised:
        TargetPortfolio(as_of=START, legs=("A",))  # type: ignore[arg-type]

    assert "TargetLeg" in str(raised.value)


# ------------------------------------------------------------ 只读行情视图


def test_market_view_reads_multiple_products_at_once() -> None:
    """一次取两个产品的 K 线，并按时间升序返回（入参故意倒序）。"""

    first = make_bars([1, 2, 3], inst_id="XAAPL-USDT")
    second = make_bars([4, 5, 6], inst_id="XMSFT-USDT")
    view = make_view(
        {"XAAPL": {BAR: list(reversed(first))}, "XMSFT": {BAR: second}},
        as_of=START + timedelta(hours=2),
    )

    assert view.product_keys == ("XAAPL", "XMSFT")
    bars = view.bars(["XAAPL", "XMSFT"], BAR)

    assert list(bars) == ["XAAPL", "XMSFT"]
    assert [item.open_time for item in bars["XAAPL"]] == sorted(
        item.open_time for item in bars["XAAPL"]
    )
    assert len(bars["XAAPL"]) == 3


def test_market_view_reports_every_missing_product() -> None:
    view = make_view()

    with pytest.raises(ValidationError) as raised:
        view.bars(["XAAPL", "XTSLA"], BAR)

    assert "XTSLA" in str(raised.value)
    assert "XAAPL" not in str(raised.value)


def test_market_view_reports_missing_bar_period() -> None:
    view = make_view()

    with pytest.raises(ValidationError) as raised:
        view.bars(["XAAPL"], "4h")

    assert "4h" in str(raised.value)


def test_market_view_computes_indicator_for_multiple_products() -> None:
    """SMA(3) 在第 3 根起成形；两个产品各自独立计算，同一视图重复调用结果相同。"""

    view = make_view()

    first = view.indicators(["XAAPL", "XMSFT"], "sma", BAR, {"period": 3})
    second = view.indicators(["XAAPL", "XMSFT"], "sma", BAR, {"period": 3})

    assert first == second
    assert first["XAAPL"] == compute("sma", view.bars(["XAAPL"], BAR)["XAAPL"], {"period": 3})
    assert [point.values["sma"] for point in first["XAAPL"].points] == [
        None,
        None,
        Decimal(2),
        Decimal(3),
        Decimal(4),
    ]


def test_market_view_exposes_relation_matrix() -> None:
    view = make_view()

    assert view.matrix["XAAPL"]["XAAPL"] == 1.0
    assert view.matrix["XAAPL"]["XMSFT"] == 0.0


def test_market_view_is_read_only() -> None:
    source = {"XAAPL": {BAR: make_bars([1, 2, 3])}}
    view = make_view(source)

    with pytest.raises(FrozenInstanceError):
        view.as_of = START  # type: ignore[misc]
    with pytest.raises(TypeError):
        view.candles["XAAPL"][BAR] = ()  # type: ignore[index]

    source["XAAPL"][BAR].append(make_bars([9], inst_id="XAAPL-USDT")[0])
    assert len(view.bars(["XAAPL"], BAR)["XAAPL"]) == 3


def test_market_view_rejects_matrix_from_another_moment() -> None:
    with pytest.raises(ValidationError) as raised:
        MarketView(
            as_of=START,
            candles={"XAAPL": {BAR: make_bars([1, 2, 3])}},
            matrix=make_matrix(("XAAPL",), as_of=START + timedelta(hours=1)),
        )

    assert "as_of" in str(raised.value)


def test_market_view_rejects_upstream_bar_alias() -> None:
    with pytest.raises(ValidationError) as raised:
        make_view({"XAAPL": {"1H": make_bars([1, 2, 3], bar="1h")}})

    assert "1H" in str(raised.value)


def test_market_view_rejects_mixed_timeframe() -> None:
    with pytest.raises(ValidationError) as raised:
        make_view({"XAAPL": {BAR: make_bars([1, 2, 3], bar="4h")}})

    assert "4h" in str(raised.value)


# ------------------------------------------------------------ 策略协议与注册表


def test_evaluate_takes_only_the_view() -> None:
    parameters = list(inspect.signature(Strategy.evaluate).parameters)

    assert parameters == ["self", "view"]
    # `from __future__ import annotations` 下注解是字符串，两种形态都认。
    assert inspect.signature(Strategy.evaluate).return_annotation in (
        TargetPortfolio,
        "TargetPortfolio",
    )


def test_registry_resolves_strategy_by_meta_name() -> None:
    assert get_strategy("example_follow_close") is ExampleStrategy
    assert "example_follow_close" in list_strategies()


def test_unknown_strategy_name_is_rejected() -> None:
    with pytest.raises(ValidationError) as raised:
        get_strategy("no_such_strategy")

    assert "no_such_strategy" in str(raised.value)


def test_duplicate_strategy_registration_is_rejected() -> None:
    class Duplicate:
        meta = StrategyMeta(name="example_duplicate", title="重复登记")
        param_schema: tuple[Param, ...] = ()
        requires = Requirements(bar=BAR, lookback=1)

        def evaluate(self, view: MarketView) -> TargetPortfolio:
            return TargetPortfolio(as_of=view.as_of, legs=())

    assert register_strategy(Duplicate) is Duplicate  # type: ignore[arg-type]
    with pytest.raises(InvariantViolation):
        register_strategy(Duplicate)  # type: ignore[arg-type]


def test_registration_rejects_bad_param_defaults() -> None:
    class BadDefault:
        meta = StrategyMeta(name="example_bad_default", title="默认值越界")
        param_schema = (Param("period", "周期", "int", 999, 1, 10),)
        requires = Requirements(bar=BAR, lookback=1)

        def evaluate(self, view: MarketView) -> TargetPortfolio:
            return TargetPortfolio(as_of=view.as_of, legs=())

    with pytest.raises(ValidationError) as raised:
        register_strategy(BadDefault)  # type: ignore[arg-type]

    assert "period" in str(raised.value)
    assert "example_bad_default" not in list_strategies()


def test_evaluate_is_deterministic_on_the_same_view() -> None:
    view = make_view()
    strategy = ExampleStrategy()

    first = strategy.evaluate(view)
    second = strategy.evaluate(view)

    assert isinstance(first, TargetPortfolio)
    assert first == second
    # 两个产品收盘价都上涨 → 两条多头腿，敞口是权重之和。
    assert first.net_exposure == Decimal("0.50")


# ------------------------------------------------------------ 参数 schema 校验


def test_params_fill_defaults_and_normalize_floats() -> None:
    schema = (
        Param("period", "周期", "int", 20, 1, 500),
        Param("threshold", "阈值", "float", 1.0, 0.0, 5.0),
    )

    resolved = resolve_params(schema, {"threshold": 2})

    assert resolved == {"period": 20, "threshold": 2.0}


@pytest.mark.parametrize(
    ("schema", "supplied", "field"),
    [
        ((Param("period", "周期", "int", 20, 1, 500),), {"unknown": 1}, "unknown"),
        ((Param("period", "周期", "int", 20, 1, 500),), {"period": 1.5}, "period"),
        ((Param("period", "周期", "int", 20, 1, 500),), {"period": True}, "period"),
        ((Param("period", "周期", "int", 20, 1, 500),), {"period": 0}, "period"),
        ((Param("period", "周期", "int", 20, 1, 500),), {"period": 501}, "period"),
    ],
)
def test_params_reject_invalid_input(
    schema: tuple[Param, ...], supplied: dict[str, object], field: str
) -> None:
    with pytest.raises(ValidationError) as raised:
        resolve_params(schema, supplied)  # type: ignore[arg-type]

    assert field in str(raised.value)


def test_params_reject_duplicate_schema_field() -> None:
    schema = (
        Param("period", "周期", "int", 20, 1, 500),
        Param("period", "再次声明", "int", 10, 1, 500),
    )

    with pytest.raises(InvariantViolation) as raised:
        resolve_params(schema)

    assert "period" in str(raised.value)


# ------------------------------------------------------- 本域的结构性约束


def _strategy_sources() -> list[Path]:
    return sorted(STRATEGY_DIR.rglob("*.py"))


def _relative(path: Path) -> str:
    return path.relative_to(STRATEGY_DIR).as_posix()


def test_strategy_imports_no_io_layers() -> None:
    """`app/strategy` 的计算代码不导入数据库、HTTP 客户端与交易所适配层。

    三个模块是 IO 与事务边界，不参与计算：

    - `model.py`：表定义必须声明在 `app.db.Base` 上（本域表结构的唯一来源）；
    - `service.py`：模板投影、实例读写与回放编排（T3.3），与 `app/opportunity/service.py`
      同一分工——取数、写库、事务边界都在这里，组合计算仍然只经组件与模板。
    - `approval.py`：生命周期阶段的唯一写入口（T3.6）。它是命令而不是计算——「哪些转移
      合法」「报告是否达标」这些规则本身是纯函数，`tests/strategy/test_approval.py` 的
      全组合用例不碰库；落库的那一步（改阶段 + 写一条审批记录）必须在这里完成，否则
      又可以绕开状态机直接改阶段。
    - `management.py`：v6 用户策略、版本、版本标的与回测关联的读写编排（B6），与
      `service.py` 同一分工；规则校验在 `rules.py`，本文件只负责事务与落库。

    其余模块逐文件检查，因此把 IO 带进计算模块（含 components / templates / builtin）
    会红。
    """

    io_boundary = frozenset({"model.py", "service.py", "approval.py", "management.py"})
    forbidden = ("app.db", "app.exchange", "session", "httpx")
    violations: list[str] = []
    for path in _strategy_sources():
        if _relative(path) in io_boundary:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                for token in forbidden:
                    if token in module:
                        violations.append(f"{_relative(path)}:{node.lineno}: {module}")

    assert not violations, "\n".join(violations)


def test_strategy_has_no_three_value_action_tokens() -> None:
    """策略对外的形状是目标组合，不出现单标的的三值动作。"""

    pattern = re.compile(r"BUY|SELL|HOLD")
    hits = [
        f"{_relative(path)}:{index}"
        for path in _strategy_sources()
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if pattern.search(line)
    ]

    assert not hits, "\n".join(hits)

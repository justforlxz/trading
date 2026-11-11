"""组合生成：约束求值、权重归一化与按类别的数量换算。

全部是纯函数：给定同一份输入两次调用得到同一份输出，不连库、不看时钟、不读行情源。
数量换算用真实的 `ct_val` / `lotSz` 夹具（`tests.factories.instruments` 的永续与现货
样本），断言的是手算出来的已知答案，不是实现里再算一遍。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core import RiskBlocked, ValidationError
from app.strategy import (
    PortfolioConstraints,
    TargetLeg,
    TargetQuantity,
    build_target,
    check_constraints,
    normalize_weights,
    target_quantity,
)
from tests.factories.instruments import make_ref, make_swap_ref

START = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)
TOLERANCE = Decimal("1e-9")


def close(actual: Decimal, expected: Decimal) -> bool:
    """1e-9 容差内的相等：除法得到的理论值不要求逐字相同的位数。"""

    return abs(actual - expected) <= TOLERANCE


def make_constraints(**overrides: object) -> PortfolioConstraints:
    """一份全部放宽的约束，用例只覆盖自己关心的那一项。"""

    values: dict[str, object] = {
        "max_leg_weight": Decimal("1"),
        "max_long_weight": Decimal("1"),
        "max_short_weight": Decimal("1"),
        "min_leg_weight": Decimal("0"),
        "max_legs": 5,
    }
    values.update(overrides)
    return PortfolioConstraints(**values)  # type: ignore[arg-type]


# ------------------------------------------------------------------ 归一化


def test_normalize_weights_scales_absolute_weights_to_one() -> None:
    """0.3 多头 + 0.1 空头 → 0.75 / 0.25，绝对值之和为 1。"""

    legs = (
        TargetLeg("A", "long", Decimal("0.3")),
        TargetLeg("B", "short", Decimal("0.1")),
    )

    normalized = normalize_weights(legs)

    assert [leg.target_weight for leg in normalized] == [Decimal("0.75"), Decimal("0.25")]
    assert sum(leg.target_weight for leg in normalized) == Decimal("1")
    assert [leg.product_key for leg in normalized] == ["A", "B"]


def test_normalize_weights_keeps_weights_that_already_sum_to_one() -> None:
    legs = (
        TargetLeg("A", "long", Decimal("0.6")),
        TargetLeg("B", "short", Decimal("0.4")),
    )

    normalized = normalize_weights(legs)

    assert [leg.target_weight for leg in normalized] == [Decimal("0.6"), Decimal("0.4")]


def test_normalize_weights_allows_no_legs() -> None:
    assert normalize_weights(()) == ()


def test_normalize_weights_rejects_weights_summing_to_zero() -> None:
    """全部为 0 时没有比例可依，拒绝而不是编一个权重出来。"""

    legs = (TargetLeg("A", "long", Decimal("0")),)

    with pytest.raises(ValidationError) as raised:
        normalize_weights(legs)

    assert "0" in str(raised.value)


# -------------------------------------------------------------- 目标组合生成


def test_build_target_normalizes_and_derives_net_exposure() -> None:
    """0.3 多头 + 0.1 空头归一化为 0.75 / 0.25，净敞口 0.5。"""

    portfolio = build_target(
        (TargetLeg("A", "long", Decimal("0.3")), TargetLeg("B", "short", Decimal("0.1"))),
        make_constraints(),
        as_of=START,
    )

    assert portfolio.as_of == START
    assert [leg.target_weight for leg in portfolio.legs] == [Decimal("0.75"), Decimal("0.25")]
    assert close(portfolio.net_exposure, Decimal("0.5"))


def test_build_target_allows_no_legs() -> None:
    portfolio = build_target((), make_constraints(), as_of=START)

    assert portfolio.legs == ()
    assert portfolio.net_exposure == Decimal(0)


def test_build_target_keeps_absolute_weights_summing_to_one() -> None:
    """三腿各 0.1 归一化后是循环小数：权重之和与 1 的差必须在 1e-9 以内。"""

    legs = tuple(TargetLeg(key, "long", Decimal("0.1")) for key in ("A", "B", "C"))

    portfolio = build_target(legs, make_constraints(max_legs=3), as_of=START)

    total = sum((leg.target_weight for leg in portfolio.legs), Decimal(0))
    assert abs(total - Decimal("1")) <= TOLERANCE
    assert close(portfolio.net_exposure, Decimal("1"))


def test_build_target_rejects_leg_over_single_instrument_cap() -> None:
    """[0.6, 0.6] 配单标高 0.5：越限抛 RiskBlocked，不静默压到 0.5。"""

    legs = (
        TargetLeg("A", "long", Decimal("0.6")),
        TargetLeg("B", "long", Decimal("0.6")),
    )

    with pytest.raises(RiskBlocked) as raised:
        build_target(legs, make_constraints(max_leg_weight=Decimal("0.5")), as_of=START)

    assert raised.value.rule == "max_leg_weight"
    assert "0.6" in raised.value.detail


def test_build_target_rejects_more_legs_than_cap() -> None:
    legs = tuple(
        TargetLeg(key, "long" if index % 2 == 0 else "short", Decimal("0.25"))
        for index, key in enumerate(("A", "B", "C", "D"))
    )

    with pytest.raises(RiskBlocked) as raised:
        build_target(legs, make_constraints(max_legs=3), as_of=START)

    assert raised.value.rule == "max_legs"


def test_build_target_accepts_legs_that_reach_the_minimum_after_normalization() -> None:
    """两腿各 0.2（合计 0.4）配最小腿权重 0.25：作为比例，归一化后是 0.5 与 0.5。

    权重是相对比例（见 `normalize_weights`），在请求阶段按 0.2 判下限会把这条合法
    输入误拒，所以最小腿权重只在归一化之后判。
    """

    legs = (
        TargetLeg("A", "long", Decimal("0.2")),
        TargetLeg("B", "short", Decimal("0.2")),
    )

    portfolio = build_target(legs, make_constraints(min_leg_weight=Decimal("0.25")), as_of=START)

    assert [leg.target_weight for leg in portfolio.legs] == [Decimal("0.5"), Decimal("0.5")]


def test_build_target_rejects_leg_below_min_weight_after_normalization() -> None:
    """0.3 与 0.05 归一化后是 0.857… 与 0.143…，后者仍低于 0.2，必须拒绝。"""

    legs = (
        TargetLeg("A", "long", Decimal("0.3")),
        TargetLeg("B", "short", Decimal("0.05")),
    )

    with pytest.raises(RiskBlocked) as raised:
        build_target(legs, make_constraints(min_leg_weight=Decimal("0.2")), as_of=START)

    assert raised.value.rule == "min_leg_weight"
    assert "0.142" in raised.value.detail


def test_build_target_rejects_long_total_over_cap() -> None:
    legs = (
        TargetLeg("A", "long", Decimal("0.3")),
        TargetLeg("B", "long", Decimal("0.3")),
        TargetLeg("C", "short", Decimal("0.4")),
    )

    with pytest.raises(RiskBlocked) as raised:
        build_target(legs, make_constraints(max_long_weight=Decimal("0.5")), as_of=START)

    assert raised.value.rule == "max_long_weight"


def test_build_target_rejects_short_total_over_cap() -> None:
    legs = (
        TargetLeg("A", "long", Decimal("0.4")),
        TargetLeg("B", "short", Decimal("0.3")),
        TargetLeg("C", "short", Decimal("0.3")),
    )

    with pytest.raises(RiskBlocked) as raised:
        build_target(legs, make_constraints(max_short_weight=Decimal("0.5")), as_of=START)

    assert raised.value.rule == "max_short_weight"


def test_build_target_rechecks_constraints_after_normalization() -> None:
    """总权重不足 1 时归一化会放大：放大后越限同样要被拦下。"""

    legs = (
        TargetLeg("A", "long", Decimal("0.2")),
        TargetLeg("B", "long", Decimal("0.2")),
    )

    with pytest.raises(RiskBlocked) as raised:
        build_target(legs, make_constraints(max_leg_weight=Decimal("0.45")), as_of=START)

    assert raised.value.rule == "max_leg_weight"


def test_build_target_rejects_naive_as_of() -> None:
    with pytest.raises(ValidationError) as raised:
        build_target((), make_constraints(), as_of=datetime(2026, 11, 10))

    assert "as_of" in str(raised.value)


def test_build_target_rejects_non_leg_items() -> None:
    with pytest.raises(ValidationError) as raised:
        build_target(("A",), make_constraints(), as_of=START)  # type: ignore[arg-type]

    assert "TargetLeg" in str(raised.value)


def test_check_constraints_passes_a_portfolio_inside_every_limit() -> None:
    """五项边界都不越界时什么都不做：不抛异常，也不改写权重。"""

    legs = (
        TargetLeg("A", "long", Decimal("0.4")),
        TargetLeg("B", "short", Decimal("0.4")),
    )

    check_constraints(legs, make_constraints())


def test_check_constraints_reports_the_violated_rule() -> None:
    """拒绝时给出规则名：上层按规则统计拒绝分布，用户能读到具体原因。"""

    legs = (
        TargetLeg("A", "long", Decimal("0.4")),
        TargetLeg("B", "long", Decimal("0.4")),
        TargetLeg("C", "short", Decimal("0.2")),
    )

    with pytest.raises(RiskBlocked) as raised:
        check_constraints(legs, make_constraints(max_long_weight=Decimal("0.7")))

    assert raised.value.rule == "max_long_weight"
    assert "0.8" in raised.value.detail


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"max_leg_weight": Decimal("-0.1")}, "max_leg_weight"),
        ({"max_leg_weight": 0.5}, "max_leg_weight"),
        ({"max_long_weight": Decimal("NaN")}, "max_long_weight"),
        ({"min_leg_weight": Decimal("-0.1")}, "min_leg_weight"),
        ({"max_legs": 0}, "max_legs"),
        ({"max_legs": 2.5}, "max_legs"),
        ({"min_leg_weight": Decimal("0.5"), "max_leg_weight": Decimal("0.3")}, "min_leg_weight"),
    ],
)
def test_constraints_reject_invalid_values(overrides: dict[str, object], field: str) -> None:
    with pytest.raises(ValidationError) as raised:
        make_constraints(**overrides)

    assert field in str(raised.value)


# -------------------------------------------------------------- 数量换算


def test_spot_quantity_uses_base_unit() -> None:
    """现货 `XAAPL-USDT`：0.5 × 1000 / 250 = 2 个标的币，单位 base。"""

    leg = TargetLeg("AAPL", "long", Decimal("0.5"))
    result = target_quantity(leg, make_ref(), price=Decimal("250"), capital=Decimal("1000"))

    assert isinstance(result, TargetQuantity)
    assert result.inst_id == "XAAPL-USDT"
    assert result.unit == "base"
    assert result.qty == Decimal("2")
    assert close(result.discarded, Decimal("0"))


def test_spot_quantity_ignores_ct_val() -> None:
    """现货没有合约面值：即使输入带上 `ct_val` 也不参与换算。"""

    leg = TargetLeg("AAPL", "long", Decimal("0.5"))
    without = target_quantity(leg, make_ref(), price=Decimal("250"), capital=Decimal("1000"))
    with_ct_val = target_quantity(
        leg, make_ref(ct_val=Decimal("7")), price=Decimal("250"), capital=Decimal("1000")
    )

    assert with_ct_val.qty == without.qty
    assert with_ct_val.unit == "base"


def test_swap_quantity_uses_contract_unit() -> None:
    """永续 `AAPL-USDT-SWAP`：0.5 × 1000 / (200 × 0.1) = 25 张合约，单位 contract。"""

    leg = TargetLeg("AAPL", "short", Decimal("0.5"))
    instrument = make_swap_ref(ct_val=Decimal("0.1"), lot_size=Decimal("0.01"))

    result = target_quantity(leg, instrument, price=Decimal("200"), capital=Decimal("1000"))

    assert isinstance(result, TargetQuantity)
    assert result.inst_id == "AAPL-USDT-SWAP"
    assert result.unit == "contract"
    assert result.qty == Decimal("25")
    assert close(result.discarded, Decimal("0"))


def test_spot_quantity_is_lot_multiple_and_records_the_remainder() -> None:
    """500 / 3 = 166.666666…，按 lotSz 0.00001 向下取整到 166.66666，差值为舍弃数量。"""

    leg = TargetLeg("AAPL", "long", Decimal("0.5"))
    theoretical = Decimal("500") / Decimal("3")

    result = target_quantity(
        leg, make_ref(lot_size=Decimal("0.00001")), price=Decimal("3"), capital=Decimal("1000")
    )

    assert result.qty == Decimal("166.66666")
    assert result.qty % Decimal("0.00001") == 0
    assert result.qty <= theoretical
    assert close(result.discarded, theoretical - result.qty)
    assert result.discarded > 0


def test_swap_quantity_is_lot_multiple_and_records_the_remainder() -> None:
    """500 / (200 × 0.3) = 8.3333…，按 lotSz 0.01 向下取整到 8.33。"""

    leg = TargetLeg("AAPL", "short", Decimal("0.5"))
    instrument = make_swap_ref(ct_val=Decimal("0.3"), lot_size=Decimal("0.01"))
    theoretical = Decimal("500") / (Decimal("200") * Decimal("0.3"))

    result = target_quantity(leg, instrument, price=Decimal("200"), capital=Decimal("1000"))

    assert result.qty == Decimal("8.33")
    assert result.qty % Decimal("0.01") == 0
    assert close(result.discarded, theoretical - result.qty)
    assert result.discarded > 0


def test_swap_quantity_requires_ct_val() -> None:
    leg = TargetLeg("AAPL", "long", Decimal("0.5"))

    with pytest.raises(ValidationError) as raised:
        target_quantity(
            leg, make_swap_ref(ct_val=None), price=Decimal("200"), capital=Decimal("1000")
        )

    assert "ct_val" in str(raised.value)


@pytest.mark.parametrize("missing", ["lot_size", "price", "capital"])
def test_quantity_rejects_missing_or_non_positive_inputs(missing: str) -> None:
    leg = TargetLeg("AAPL", "long", Decimal("0.5"))
    instrument = make_ref()
    price = Decimal("250")
    capital = Decimal("1000")
    if missing == "lot_size":
        instrument = make_ref(lot_size=None)
    elif missing == "price":
        price = Decimal("0")
    else:
        capital = Decimal("0")

    with pytest.raises(ValidationError) as raised:
        target_quantity(leg, instrument, price=price, capital=capital)

    assert missing in str(raised.value)


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"price": 250}, "price"),
        ({"price": Decimal("-1")}, "price"),
        ({"capital": 1000}, "capital"),
        ({"capital": Decimal("NaN")}, "capital"),
    ],
)
def test_quantity_rejects_non_decimal_or_non_positive_numbers(
    kwargs: dict[str, object], field: str
) -> None:
    leg = TargetLeg("AAPL", "long", Decimal("0.5"))
    arguments: dict[str, object] = {"price": Decimal("250"), "capital": Decimal("1000")}
    arguments.update(kwargs)

    with pytest.raises(ValidationError) as raised:
        target_quantity(leg, make_ref(), **arguments)  # type: ignore[arg-type]

    assert field in str(raised.value)


def test_quantity_shape_is_the_same_for_both_classes() -> None:
    """两条换算路径产出同一个形状，上层不必按类别分派。"""

    leg = TargetLeg("AAPL", "long", Decimal("0.5"))
    spot = target_quantity(leg, make_ref(), price=Decimal("250"), capital=Decimal("1000"))
    swap = target_quantity(
        leg,
        make_swap_ref(ct_val=Decimal("0.1"), lot_size=Decimal("0.01")),
        price=Decimal("200"),
        capital=Decimal("1000"),
    )

    for result in (spot, swap):
        assert isinstance(result, TargetQuantity)
        assert isinstance(result.qty, Decimal)
    assert {spot.unit, swap.unit} == {"base", "contract"}


def test_quantity_accepts_instrument_ref_only() -> None:
    """换算只读标的快照与价格，不碰数据库模型。"""

    leg = TargetLeg("AAPL", "long", Decimal("0.5"))

    instrument = make_ref(inst_id="XTSLA-USDT")
    result = target_quantity(leg, instrument, price=Decimal("250"), capital=Decimal("1000"))

    assert result.inst_id == "XTSLA-USDT"
    assert result.unit == "base"


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"inst_id": ""}, "inst_id"),
        ({"unit": ""}, "unit"),
        ({"qty": 1}, "qty"),
        ({"qty": Decimal("-1")}, "qty"),
        ({"discarded": 0.5}, "discarded"),
    ],
)
def test_target_quantity_rejects_invalid_fields(kwargs: dict[str, object], field: str) -> None:
    defaults: dict[str, object] = {
        "inst_id": "XAAPL-USDT",
        "qty": Decimal("1"),
        "unit": "base",
        "discarded": Decimal("0"),
    }
    defaults.update(kwargs)

    with pytest.raises(ValidationError) as raised:
        TargetQuantity(**defaults)  # type: ignore[arg-type]

    assert field in str(raised.value)

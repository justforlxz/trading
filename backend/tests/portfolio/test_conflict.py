"""冲突检测与全局敞口：纯函数，已知答案。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core import ValidationError
from app.portfolio import (
    ExposureLeg,
    aggregate_exposure,
    net_exposure,
    product_conflicts,
)


def leg(
    instance: str,
    product: str,
    direction: str,
    weight: str,
    notional: str | None = None,
) -> ExposureLeg:
    weight_value = Decimal(weight)
    return ExposureLeg(
        instance_id=instance,
        product_key=product,
        direction=direction,
        weight=weight_value,
        notional=Decimal(notional) if notional is not None else weight_value * Decimal("1000"),
    )


def test_opposite_directions_on_the_same_product_are_reported_with_both_sides() -> None:
    """两个策略对同一产品持相反方向：返回该标的，并给出两侧策略标识。"""

    conflicts = product_conflicts(
        [leg("si_a", "AAPL", "long", "0.5"), leg("si_b", "AAPL", "short", "0.25")]
    )

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.product_key == "AAPL"
    assert conflict.long_instance_ids == ("si_a",)
    assert conflict.short_instance_ids == ("si_b",)


def test_same_direction_is_duplicate_holding_not_a_conflict() -> None:
    """同向重复持仓不属于多空冲突；冲突列表为空。"""

    assert (
        product_conflicts([leg("si_a", "AAPL", "long", "0.5"), leg("si_b", "AAPL", "long", "0.3")])
        == ()
    )

    # 同向的两个策略都被列进同一侧，不去重也不丢。
    conflicts = product_conflicts(
        [
            leg("si_a", "AAPL", "long", "0.5"),
            leg("si_b", "AAPL", "long", "0.3"),
            leg("si_c", "AAPL", "short", "0.1"),
        ]
    )
    assert conflicts[0].long_instance_ids == ("si_a", "si_b")


def test_multiple_instances_on_the_same_side_are_all_listed() -> None:
    conflicts = product_conflicts(
        [
            leg("si_b", "BTC", "short", "0.1"),
            leg("si_a", "BTC", "long", "0.2"),
            leg("si_c", "BTC", "short", "0.3"),
        ]
    )

    assert [(c.product_key, c.long_instance_ids, c.short_instance_ids) for c in conflicts] == [
        ("BTC", ("si_a",), ("si_b", "si_c"))
    ]


def test_global_net_exposure_is_long_minus_short() -> None:
    """净敞口 = 各策略多头权重之和 − 空头权重之和（1e-9 容差内精确相等）。"""

    legs = [
        leg("si_a", "AAPL", "long", "0.60"),
        leg("si_a", "MSFT", "long", "0.15"),
        leg("si_b", "TSLA", "short", "0.40"),
        leg("si_b", "AAPL", "short", "0.05"),
    ]

    overview = aggregate_exposure(legs, equity=Decimal("1000"))

    assert abs(overview.net_exposure - Decimal("0.30")) < Decimal("1e-9")
    assert overview.net_exposure == overview.long_exposure - overview.short_exposure
    assert overview.gross_exposure == overview.long_exposure + overview.short_exposure
    assert overview.gross_exposure == Decimal("1.20")
    assert overview.open_positions == 4
    # AAPL 净权重 = 0.60 − 0.05 = 0.55，是单一产品的最大绝对值。
    assert overview.product_count == 3
    assert overview.largest_position_share == Decimal("0.55")
    assert overview.conflicts[0].product_key == "AAPL"


def test_empty_portfolio_has_zero_exposure() -> None:
    overview = aggregate_exposure([], equity=Decimal("0"))

    assert overview.net_exposure == overview.gross_exposure == Decimal("0")
    assert overview.open_positions == 0
    assert overview.conflicts == ()
    assert overview.largest_position_share == Decimal("0")


def test_concentration_is_product_notional_over_total_budget() -> None:
    """不同预算的策略不能把权重直接相加当集中度；统一用名义价值除以预算总和。"""

    overview = aggregate_exposure(
        [
            leg("si_big", "AAPL", "long", "0.5", notional="500"),
            leg("si_small", "MSFT", "long", "0.5", notional="50"),
        ],
        equity=Decimal("1100"),
    )

    assert abs(overview.largest_position_share - Decimal("500") / Decimal("1100")) < Decimal(
        "1e-12"
    )


def test_net_exposure_rejects_unknown_directions() -> None:
    with pytest.raises(ValidationError):
        net_exposure([("flat", Decimal("0.5"))])

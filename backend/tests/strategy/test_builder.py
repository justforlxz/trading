"""策略构建器不变量（AC2/AC3/AC8）：权重归一、约束强制、确定性与可解释。"""

from decimal import Decimal

import pytest

from app.strategy.core.builder import BuiltLeg, LegCandidate, allocate, build_legs
from app.strategy.core.constraints import (
    ConstraintViolation,
    check_legs,
    gross_exposure,
    net_exposure,
)
from app.strategy.core.hash import strategy_key

TOL = Decimal("1e-9")
LIMITS = {
    "max_position_weight": Decimal("0.7"),
    "max_gross_exposure": Decimal("1"),
    "max_net_exposure": Decimal("1"),
    "min_legs": 2,
    "max_legs": 6,
    "window_bars": 60,
}


def _candidate(
    instrument_id: int,
    side: str,
    *,
    ret_20d: float | None = None,
    ret_5d: float | None = None,
    vol_20d: float | None = None,
    **metrics: float,
) -> LegCandidate:
    payload: dict[str, float] = dict(metrics)
    for key, value in (
        ("ret_20d", ret_20d),
        ("ret_5d", ret_5d),
        ("vol_20d", vol_20d),
    ):
        if value is not None:
            payload[key] = value
    return LegCandidate(
        instrument_id=instrument_id,
        inst_id=f"SYM{instrument_id}-USDT-SWAP",
        side=side,
        metrics=payload,
    )


def _build(candidates, **overrides):
    limits = {**LIMITS, **overrides}
    return build_legs(candidates, templates=["trend_following"], **limits)


def test_mixed_book_normalizes_gross_and_keeps_signed_net() -> None:
    """多空混合：|w| 之和恰为 1，净敞口等于各腿符号权重之和。"""

    legs = _build(
        [
            _candidate(1, "long", ret_20d=0.10, vol_20d=0.02),
            _candidate(2, "short", ret_20d=-0.05, vol_20d=0.02),
        ]
    )

    weights = {leg.instrument_id: leg.target_weight for leg in legs}
    assert gross_exposure(legs) == pytest.approx(1, abs=1e-9)
    # 手算：分数 0.10/0.02=5 与 0.05/0.02=2.5，按 2:1 分配，净敞口 = 1/3。
    assert weights[1] == pytest.approx(Decimal("0.6666666667"), abs=TOL)
    assert weights[2] == pytest.approx(Decimal("-0.3333333333"), abs=TOL)
    assert net_exposure(legs) == pytest.approx(Decimal(1) / 3, abs=TOL)
    assert [leg.rank for leg in legs] == [1, 2]
    assert legs[0].instrument_id == 1


def test_every_leg_carries_metric_and_window_rationale() -> None:
    legs = _build(
        [
            _candidate(1, "long", ret_20d=0.10, vol_20d=0.02),
            _candidate(2, "short", ret_20d=-0.08, vol_20d=0.02),
        ]
    )

    for leg in legs:
        assert leg.rationale
        assert "window=60" in leg.rationale
        assert "ret_20d=" in leg.rationale


def test_alias_template_expands_to_members() -> None:
    """`relative_value` 是模板别名，不能被当成未知模板拒绝（AC10 的请求体）。"""

    legs = build_legs(
        [
            _candidate(1, "long", coefficient=0.87, stability=0.75, best_lag=-1),
            _candidate(2, "short", coefficient=-0.66, stability=0.5, best_lag=2),
        ],
        templates=["relative_value"],
        **LIMITS,
    )

    assert len(legs) == 2
    assert all("coefficient=" in leg.rationale for leg in legs)


def test_unknown_template_is_rejected() -> None:
    with pytest.raises(ConstraintViolation) as caught:
        build_legs(
            [_candidate(1, "long", ret_20d=0.1), _candidate(2, "short", ret_20d=-0.1)],
            templates=["no_such_template"],
            **LIMITS,
        )

    assert caught.value.code == "strategy_unknown_template"
    assert caught.value.status_code == 422
    assert caught.value.details["unknown"] == ["no_such_template"]


def test_position_cap_beyond_allocation_is_rejected_not_clipped() -> None:
    with pytest.raises(ConstraintViolation) as caught:
        _build(
            [
                _candidate(1, "long", ret_20d=0.10, vol_20d=0.02),
                _candidate(2, "short", ret_20d=-0.10, vol_20d=0.02),
            ],
            max_position_weight=Decimal("0.4"),
        )

    assert caught.value.code == "strategy_position_limit"


def test_gross_exposure_cap_is_enforced() -> None:
    with pytest.raises(ConstraintViolation) as caught:
        _build(
            [
                _candidate(1, "long", ret_20d=0.10, vol_20d=0.02),
                _candidate(2, "long", ret_20d=0.10, vol_20d=0.02),
            ],
            max_gross_exposure=Decimal("0.9"),
        )

    assert caught.value.code == "strategy_gross_exposure_exceeded"


def test_net_exposure_cap_is_enforced() -> None:
    with pytest.raises(ConstraintViolation) as caught:
        _build(
            [
                _candidate(1, "long", ret_20d=0.10, vol_20d=0.02),
                _candidate(2, "long", ret_20d=0.10, vol_20d=0.02),
            ],
            max_net_exposure=Decimal("0.5"),
        )

    assert caught.value.code == "strategy_net_exposure_exceeded"


def test_position_limit_violation_is_detected_by_check_legs() -> None:
    legs = [
        LegCandidate(1, "SYM1-USDT-SWAP", "long", {"ret_20d": 0.1}),
        LegCandidate(2, "SYM2-USDT-SWAP", "short", {"ret_20d": -0.1}),
    ]
    built = build_legs(legs, templates=["trend_following"], **LIMITS)

    oversized = [
        type(built[0])(
            instrument_id=built[0].instrument_id,
            inst_id=built[0].inst_id,
            side="long",
            target_weight=Decimal("0.7"),
            rationale="x",
        ),
        type(built[1])(
            instrument_id=built[1].instrument_id,
            inst_id=built[1].inst_id,
            side="short",
            target_weight=Decimal("-0.3"),
            rationale="x",
        ),
    ]
    with pytest.raises(ConstraintViolation) as caught:
        check_legs(
            oversized,
            min_legs=2,
            max_legs=6,
            max_position_weight=Decimal("0.6"),
            max_gross_exposure=Decimal("1"),
            max_net_exposure=Decimal("1"),
        )

    assert caught.value.code == "strategy_position_limit"


def test_min_legs_is_enforced() -> None:
    with pytest.raises(ConstraintViolation) as caught:
        _build([_candidate(1, "long", ret_20d=0.1)])

    assert caught.value.code == "strategy_min_legs"


def test_max_legs_is_enforced() -> None:
    with pytest.raises(ConstraintViolation) as caught:
        _build(
            [
                _candidate(1, "long", ret_20d=0.1),
                _candidate(2, "long", ret_20d=0.1),
                _candidate(3, "long", ret_20d=0.1),
            ],
            max_legs=2,
        )

    assert caught.value.code == "strategy_max_legs"


def test_duplicate_member_is_rejected() -> None:
    with pytest.raises(ConstraintViolation) as caught:
        _build(
            [
                _candidate(1, "long", ret_20d=0.1),
                _candidate(1, "short", ret_20d=-0.1),
            ]
        )

    assert caught.value.code == "strategy_duplicate_leg"


def test_side_weight_sign_mismatch_is_rejected() -> None:
    broken = [
        BuiltLeg(1, "SYM1-USDT-SWAP", "long", Decimal("-0.5"), "x"),
        BuiltLeg(2, "SYM2-USDT-SWAP", "short", Decimal("0.5"), "x"),
    ]
    with pytest.raises(ConstraintViolation) as caught:
        check_legs(
            broken,
            min_legs=2,
            max_legs=6,
            max_position_weight=Decimal("0.6"),
            max_gross_exposure=Decimal("1"),
            max_net_exposure=Decimal("1"),
        )

    assert caught.value.code == "strategy_side_weight_mismatch"


def test_unevidenced_leg_is_rejected() -> None:
    with pytest.raises(ConstraintViolation) as caught:
        _build(
            [
                _candidate(1, "long"),
                _candidate(2, "short", ret_20d=-0.1),
            ]
        )

    assert caught.value.code == "strategy_unevidenced_leg"


def test_allocate_sums_to_one_and_respects_cap() -> None:
    weights = allocate([1.0, 1.0, 1.0], cap=Decimal("0.4"))

    assert sum(weights) == Decimal("1")
    assert all(weight <= Decimal("0.4") + TOL for weight in weights)


def test_strategy_key_ignores_json_key_order_and_whitespace() -> None:
    first = strategy_key(
        kind="relative_value",
        target_id=1,
        templates=["relative_value"],
        params={"b": 2, "a": {"y": 1, "x": [1, 2]}},
        legs=[
            {"instrument_id": 2, "side": "short", "target_weight": "-0.4"},
            {"instrument_id": 1, "side": "long", "target_weight": "0.6"},
        ],
    )
    second = strategy_key(
        kind="relative_value",
        target_id=1,
        templates=["relative_value"],
        params={"a": {"x": [1, 2], "y": 1}, "b": 2},
        legs=[
            {"target_weight": Decimal("0.6"), "side": "long", "instrument_id": 1},
            {"side": "short", "instrument_id": 2, "target_weight": Decimal("-0.4")},
        ],
    )

    assert first == second
    changed = strategy_key(
        kind="relative_value",
        target_id=1,
        templates=["relative_value"],
        params={"a": {"x": [1, 2], "y": 1}, "b": 3},
        legs=[
            {"instrument_id": 1, "side": "long", "target_weight": "0.6"},
            {"instrument_id": 2, "side": "short", "target_weight": "-0.4"},
        ],
    )
    assert changed != first

"""保证金模型：分档 clamp、强平价纯函数、两类结算口径的差异。

档位数值全部来自冻结的上游快照
`tests/fixtures/okx/position_tiers_AAPL-USDT_2026-11-11.json`（OKX `/public/position-tiers`
逐仓 87 档，由 `scripts/record_okx_position_tiers.py` 录制），强平价与保证金用手算值
断言，不拿被测实现算出来的值反向验证。
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.backtest import (
    DEFAULT_MAX_LEVERAGE,
    HARD_MAX_LEVERAGE,
    MarginTerms,
    PositionTier,
    effective_leverage,
    initial_margin,
    liquidated_in_bar,
    liquidation_price,
    maintenance_margin,
    margin_terms,
    margin_used,
    max_loss,
    parse_position_tiers,
    tier_for,
)
from app.core import UpstreamError, ValidationError

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "okx"
TIERS_FIXTURE = FIXTURES_DIR / "position_tiers_AAPL-USDT_2026-11-11.json"

SWAP = "SWAP"
SPOT = "SPOT"
ENTRY = Decimal("100")
TOL = Decimal("1e-9")


def tiers() -> tuple[PositionTier, ...]:
    document = json.loads(TIERS_FIXTURE.read_text(encoding="utf-8"))
    return parse_position_tiers(document["position_tiers"])


# ------------------------------------------------------------------ 分档 clamp


def test_fixture_holds_the_eighty_seven_isolated_tiers() -> None:
    """冻结快照就是上游的 87 档逐仓表，档位号从 1 连续到 87。"""

    document = json.loads(TIERS_FIXTURE.read_text(encoding="utf-8"))

    assert document["meta"]["counts"]["tiers"] == 87
    assert len(tiers()) == 87
    assert [row["tier"] for row in document["position_tiers"]] == [
        str(number) for number in range(1, 88)
    ]


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ("650", Decimal("3")),  # 第 1 档：min(默认上限 3, 该档 20) = 3
        ("70000", Decimal("2.89")),  # 第 56 档：68900.01–70200
        ("110000", Decimal("2.0")),  # 第 87 档：109200.01–110500
    ],
)
def test_effective_leverage_is_clamped_by_the_tier(size: str, expected: Decimal) -> None:
    assert effective_leverage(DEFAULT_MAX_LEVERAGE, tiers(), Decimal(size)) == expected


@pytest.mark.parametrize("size", ["1", "650", "650.01", "70000", "110000"])
def test_local_cap_of_one_wins_over_every_tier(size: str) -> None:
    """本地杠杆设成 1 时，任意档位都只能用 1。"""

    assert effective_leverage(Decimal(1), tiers(), Decimal(size)) == Decimal(1)


def test_hard_cap_ten_survives_an_over_configured_cap() -> None:
    """配置把上限调到 20 也不会突破硬上限 10（第一档上游给的是 20）。"""

    assert Decimal(10) == HARD_MAX_LEVERAGE
    assert effective_leverage(Decimal(20), tiers(), Decimal("650")) == Decimal(10)


def test_size_outside_the_tier_table_is_rejected() -> None:
    """超过最后一档的规模不借用相邻档，直接报错。"""

    with pytest.raises(ValidationError):
        tier_for(tiers(), Decimal("110500.01"))


def test_malformed_tier_rows_are_upstream_errors() -> None:
    with pytest.raises(UpstreamError):
        parse_position_tiers([{"minSz": "0", "maxSz": "650", "maxLever": "20", "mmr": "1"}])
    with pytest.raises(UpstreamError):
        parse_position_tiers([{"minSz": "0", "maxSz": "650", "maxLever": "20"}])
    with pytest.raises(UpstreamError):
        parse_position_tiers([])


# ------------------------------------------------------------------ 强平价纯函数


def test_liquidation_price_matches_the_hand_calculation() -> None:
    """开仓 100、杠杆 5、mmr 0.02：距离 100 × (0.2 − 0.02) = 18，多仓 82、空仓 118。"""

    long_price = liquidation_price(
        side="long", entry_price=ENTRY, leverage=Decimal(5), maintenance_margin_rate=Decimal("0.02")
    )
    short_price = liquidation_price(
        side="short",
        entry_price=ENTRY,
        leverage=Decimal(5),
        maintenance_margin_rate=Decimal("0.02"),
    )

    assert long_price == Decimal("82")
    assert short_price == Decimal("118")


def test_liquidation_distance_grows_as_leverage_falls() -> None:
    """杠杆越大占用保证金越少，强平价就越靠近开仓价：距离随手算值严格递减。

    开仓 100、mmr 0.0125 时，杠杆 2 / 3 / 5 / 10 的距离分别是
    100 × (1/lever − 0.0125) = 48.75 / 32.0833… / 18.75 / 8.75。
    """

    for side in ("long", "short"):
        distances = [
            abs(
                liquidation_price(
                    side=side,
                    entry_price=ENTRY,
                    leverage=Decimal(leverage),
                    maintenance_margin_rate=Decimal("0.0125"),
                )
                - ENTRY
            )
            for leverage in ("2", "3", "5", "10")
        ]
        assert distances == sorted(distances, reverse=True)
        assert distances[0] == Decimal("48.75")
        assert distances[-1] == Decimal("8.75")


def test_liquidation_distance_shrinks_as_maintenance_margin_grows() -> None:
    """维持保证金率越大，留给价格波动的空间越小。"""

    for side in ("long", "short"):
        distances = [
            abs(
                liquidation_price(
                    side=side,
                    entry_price=ENTRY,
                    leverage=Decimal(3),
                    maintenance_margin_rate=Decimal(rate),
                )
                - ENTRY
            )
            for rate in ("0.0125", "0.02", "0.05", "0.2")
        ]
        assert distances == sorted(distances, reverse=True)
        assert len(set(distances)) == len(distances)


@pytest.mark.parametrize(
    ("leverage", "rate"),
    [
        ("2", "0.004"),
        ("2", "0.05"),
        ("3", "0.0125"),
        ("3", "0.2"),
        ("5", "0.004"),
        ("5", "0.05"),
        ("10", "0.004"),
        ("20", "0.04"),
    ],
)
def test_long_and_short_liquidation_are_mirrored(leverage: str, rate: str) -> None:
    """同样的开仓价、杠杆与 mmr，多空强平距必须相等（镜像）。"""

    kwargs = {
        "entry_price": ENTRY,
        "leverage": Decimal(leverage),
        "maintenance_margin_rate": Decimal(rate),
    }

    long_price = liquidation_price(side="long", **kwargs)
    short_price = liquidation_price(side="short", **kwargs)

    assert abs((ENTRY - long_price) - (short_price - ENTRY)) < TOL
    assert long_price < ENTRY < short_price


def test_a_leverage_beyond_the_maintenance_rate_has_no_liquidation_price() -> None:
    """1/杠杆 不大于 mmr 时价格无法波动，报错而不是给出负价格。"""

    with pytest.raises(ValidationError):
        liquidation_price(
            side="long",
            entry_price=ENTRY,
            leverage=Decimal(10),
            maintenance_margin_rate=Decimal("0.1"),
        )


def test_bar_touch_uses_the_adverse_extreme_of_each_side() -> None:
    level = Decimal("82")

    assert liquidated_in_bar(
        side="long", liquidation_price=level, high=Decimal("100"), low=Decimal("82")
    )
    assert not liquidated_in_bar(
        side="long", liquidation_price=level, high=Decimal("100"), low=Decimal("82.01")
    )
    assert liquidated_in_bar(
        side="short", liquidation_price=Decimal("118"), high=Decimal("118"), low=Decimal("100")
    )
    assert not liquidated_in_bar(
        side="short", liquidation_price=Decimal("118"), high=Decimal("117.99"), low=Decimal("100")
    )


# ------------------------------------------------------------------ 两类结算口径


def test_spot_has_no_leverage_no_margin_and_no_liquidation() -> None:
    terms: MarginTerms = margin_terms(
        inst_type=SPOT, side="long", entry_price=ENTRY, size=Decimal(1)
    )

    assert terms.has_margin is False
    assert terms.leverage == Decimal(1)
    assert terms.tier is None
    assert terms.liquidation_price is None
    assert margin_used(terms, Decimal("5000")) == Decimal(0)


def test_spot_max_loss_is_capped_by_the_buy_amount() -> None:
    """现货多头最多亏掉买入金额：名义金额 5000 就是上限，不是 0 也不是无限。"""

    terms = margin_terms(inst_type=SPOT, side="long", entry_price=ENTRY, size=Decimal(1))

    assert max_loss(terms, side="long", notional=Decimal("5000")) == Decimal("5000")


def test_swap_uses_the_tier_of_its_size() -> None:
    """规模 70000 落在第 56 档：杠杆 2.89、mmr 0.295，占用保证金 = 名义金额 / 2.89。"""

    terms = margin_terms(
        inst_type=SWAP,
        side="long",
        entry_price=ENTRY,
        size=Decimal("70000"),
        tiers=tiers(),
    )

    assert terms.has_margin is True
    assert terms.leverage == Decimal("2.89")
    assert terms.tier is not None
    assert terms.tier.maintenance_margin_rate == Decimal("0.295")
    assert terms.liquidation_price is not None
    assert margin_used(terms, Decimal("70000")) == initial_margin(Decimal("70000"), Decimal("2.89"))


def test_swap_max_loss_is_the_occupied_margin() -> None:
    """逐仓永续最多亏掉占用的保证金，而不是整个名义金额。"""

    terms = margin_terms(
        inst_type=SWAP,
        side="long",
        entry_price=ENTRY,
        size=Decimal("650"),
        tiers=tiers(),
    )

    assert max_loss(terms, side="long", notional=Decimal("5000")) == initial_margin(
        Decimal("5000"), terms.leverage
    )


def test_swap_short_liquidation_is_above_the_entry() -> None:
    terms = margin_terms(
        inst_type=SWAP,
        side="short",
        entry_price=ENTRY,
        size=Decimal("650"),
        tiers=tiers(),
    )

    assert terms.liquidation_price is not None
    assert terms.liquidation_price > ENTRY


def test_maintenance_margin_scales_with_notional() -> None:
    assert maintenance_margin(Decimal("70000"), Decimal("0.295")) == Decimal("20650")

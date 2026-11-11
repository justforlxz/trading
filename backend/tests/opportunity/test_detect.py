"""机会发现纯函数：评分与筛选的已知答案。

每个期望值都由「写了哪几根 K 线、给了哪个相关系数」直接反推：趋势是窗口首尾收盘价
的相对变化，腿的方向由趋势符号决定，门槛是最小趋势幅度与最小相关系数绝对值。
两条模式各自断言一次「类别不混」与「锚点不必进组合」。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core import Bar, Timeframe
from app.opportunity import (
    LEG_LIMIT,
    LONG,
    MIN_ABS_CORRELATION,
    MIN_RESONANCE,
    MIN_TREND,
    MODE_MARKET,
    MODE_TARGET,
    SHORT,
    Candidate,
    Leg,
    Observation,
    leg_of,
    market_candidates,
    target_candidate,
    trend,
)

AS_OF = datetime(2026, 11, 10, 23, 0, tzinfo=UTC)
DAY = timedelta(days=1)
START = AS_OF - DAY * 6


def bars(inst_id: str, closes: list[str], *, source: str = "okx") -> tuple[Bar, ...]:
    """按 `closes` 顺序构造连续日线；`inst_id` 只用于标识，不参与评分。"""

    return tuple(
        Bar(
            inst_id=inst_id,
            timeframe=Timeframe.parse("1d"),
            open_time=START + DAY * index,
            open=Decimal(close),
            high=Decimal(close),
            low=Decimal(close),
            close=Decimal(close),
            volume=Decimal("10"),
            confirm=True,
            source=source,
        )
        for index, close in enumerate(closes)
    )


def sample(
    product_key: str,
    closes: list[str],
    *,
    inst_type: str = "SPOT",
    source: str = "okx",
) -> Observation:
    """一个标的的样本；交易所标识用产品键派生，腿里能直接认出来源标的。"""

    return Observation(
        product_key=product_key,
        inst_id=f"{product_key}-USDT",
        inst_type=inst_type,
        source=source,
        bars=bars(f"{product_key}-USDT", closes, source=source),
    )


def test_trend_is_first_to_last_close_over_the_window() -> None:
    """100 → 110 是 +10%；100 → 90 是 -10%；顺序打乱不改变结论。"""

    assert trend(bars("A", ["100", "110"])) == pytest.approx(0.1)
    assert trend(bars("A", ["100", "90"])) == pytest.approx(-0.1)
    assert trend(bars("A", ["100", "105", "110"])) == pytest.approx(0.1)
    shuffled = tuple(reversed(bars("A", ["100", "105", "110"])))
    assert trend(shuffled) == pytest.approx(0.1)


def test_trend_is_zero_without_two_bars() -> None:
    """一根 K 线（或没有 K 线）没有方向：给 0，不补一个「不变」出来。"""

    assert trend(bars("A", ["100"])) == 0.0
    assert trend(()) == 0.0


def test_leg_of_marks_direction_and_strength() -> None:
    """上涨是 long、下跌是 short，强度是趋势幅度本身（6 位小数）。"""

    up = leg_of(sample("UP", ["100", "110"]))
    down = leg_of(sample("DOWN", ["100", "90"]))

    assert up is not None and down is not None
    assert (up.direction, up.score) == (LONG, Decimal("0.100000"))
    assert (down.direction, down.score) == (SHORT, Decimal("0.100000"))
    assert (up.product_key, up.inst_id, up.inst_type) == ("UP", "UP-USDT", "SPOT")


@pytest.mark.parametrize(
    "closes",
    [
        ["100", "100"],  # 完全不动
        ["100", "100.5"],  # 0.5%：在 1% 门槛之下
        ["100", "99.5"],  # -0.5%：同上
    ],
)
def test_leg_of_rejects_moves_below_the_threshold(closes: list[str]) -> None:
    assert leg_of(sample("FLAT", closes)) is None


def test_leg_of_accepts_exactly_the_threshold() -> None:
    """门槛是「小于才丢」：恰好 1% 的移动算有方向。"""

    leg = leg_of(sample("EDGE", ["100", "101"]))

    assert leg is not None
    assert leg.direction == LONG


def test_target_candidate_keeps_anchor_out_of_legs_when_it_has_no_direction() -> None:
    """锚点自身没有方向、邻居有方向：机会的锚点仍是它，腿里却没有它。"""

    anchor = sample("AAPL", ["100", "120", "100", "120", "100"])
    peer = sample("MSFT", ["50", "60", "50", "60", "55"])

    candidate = target_candidate(anchor, [anchor, peer], {"MSFT": 0.9}, as_of=AS_OF)

    assert candidate is not None
    assert candidate.mode == MODE_TARGET
    assert candidate.anchor_product_key == "AAPL"
    assert [leg.product_key for leg in candidate.legs] == ["MSFT"]
    assert candidate.legs[0] == Leg(
        inst_id="MSFT-USDT",
        inst_type="SPOT",
        product_key="MSFT",
        direction=LONG,
        score=Decimal("0.100000"),
    )
    assert candidate.evidence["neighbours"] == 1
    assert candidate.evidence["correlation"] == pytest.approx(0.9)


def test_target_candidate_includes_the_anchor_when_it_has_a_direction() -> None:
    """锚点自己有方向时也作为一条腿进来：锚点不是被排除，只是不被特殊对待。"""

    anchor = sample("AAPL", ["100", "110"])
    peer = sample("MSFT", ["50", "45"])

    candidate = target_candidate(anchor, [anchor, peer], {"MSFT": 0.8}, as_of=AS_OF)

    assert candidate is not None
    directions = {leg.product_key: leg.direction for leg in candidate.legs}
    assert directions == {"AAPL": LONG, "MSFT": SHORT}


def test_target_candidate_drops_unrelated_neighbours() -> None:
    """相关系数不到门槛的邻居不进候选；一个腿都不剩时不产出机会。"""

    anchor = sample("AAPL", ["100", "120", "100"])
    weak = sample("MSFT", ["50", "51", "60"])

    below = target_candidate(anchor, [weak], {"MSFT": 0.4}, as_of=AS_OF)
    missing = target_candidate(anchor, [weak], {}, as_of=AS_OF)
    undefined = target_candidate(anchor, [weak], {"MSFT": None}, as_of=AS_OF)

    assert below is None
    assert missing is None
    assert undefined is None
    assert MIN_ABS_CORRELATION == 0.5


def test_target_candidate_ranks_legs_by_strength_and_caps_them() -> None:
    """腿按强度倒序、同强度按产品键，超出上限的部分被截掉——顺序也是结果的一部分。"""

    anchor = sample("AAPL", ["100", "120", "100"])
    peers = [
        sample("AAA", ["100", "101"]),  # +1%
        sample("BBB", ["100", "130"]),  # +30%
        sample("CCC", ["100", "120"]),  # +20%
    ]
    correlations = {"AAA": 0.6, "BBB": 0.9, "CCC": 0.7}

    candidate = target_candidate(anchor, peers, correlations, as_of=AS_OF, limit=2)

    assert candidate is not None
    assert [leg.product_key for leg in candidate.legs] == ["BBB", "CCC"]
    assert candidate.score == Decimal("0.250000")  # (0.3 + 0.2) / 2
    assert LEG_LIMIT == 5


def test_target_candidate_ranks_the_anchor_like_any_other_leg() -> None:
    """锚点也是一条腿：强度最高时它排在第一位，上限截断按同一套排序生效。"""

    anchor = sample("AAPL", ["100", "200"])
    peers = [sample("MSFT", ["100", "150"])]

    candidate = target_candidate(anchor, [anchor, *peers], {"MSFT": 1.0}, as_of=AS_OF, limit=1)

    assert candidate is not None
    assert [leg.product_key for leg in candidate.legs] == ["AAPL"]


def test_market_candidates_count_each_class_separately() -> None:
    """两类各自统计：两个类别各一条机会，腿里只有本类别的标的。"""

    spot = [sample(f"S{index}", ["100", "110"], inst_type="SPOT") for index in range(5)]
    swap = [sample(f"W{index}", ["100", "90"], inst_type="SWAP") for index in range(5)]

    candidates = market_candidates({"SPOT": spot, "SWAP": swap}, as_of=AS_OF)

    assert [candidate.mode for candidate in candidates] == [MODE_MARKET, MODE_MARKET]
    assert [candidate.evidence["inst_type"] for candidate in candidates] == ["SPOT", "SWAP"]
    assert [candidate.legs[0].direction for candidate in candidates] == [LONG, SHORT]
    assert {leg.inst_type for leg in candidates[0].legs} == {"SPOT"}
    assert {leg.inst_type for leg in candidates[1].legs} == {"SWAP"}
    assert candidates[0].anchor_product_key is None
    assert candidates[0].evidence["resonance"] == pytest.approx(1.0)
    assert candidates[0].evidence["breadth"] == {
        "advancers": 5,
        "decliners": 0,
        "unchanged": 0,
        "participants": 5,
    }


def test_market_candidates_keep_only_legs_aligned_with_the_class_direction() -> None:
    """类别整体上涨时空头标的不进腿：方向不一致的标的不是这条机会的成员。"""

    group = [sample(f"S{index}", ["100", "110"]) for index in range(5)]
    group.append(sample("SHORTY", ["100", "90"]))

    candidates = market_candidates({"SPOT": group}, as_of=AS_OF)

    assert len(candidates) == 1
    assert "SHORTY" not in {leg.product_key for leg in candidates[0].legs}


def test_market_candidates_need_enough_participants_for_resonance() -> None:
    """参与标的少于共振的最小样本数时，同向程度是 `None`，不产出机会。"""

    group = [sample(f"S{index}", ["100", "110"]) for index in range(4)]

    assert market_candidates({"SPOT": group}, as_of=AS_OF) == ()


def test_market_candidates_need_a_clear_direction() -> None:
    """涨跌家数相等（3 涨 3 跌）时没有方向，即使同向程度过门槛也不产出机会。"""

    group = [sample(f"UP{index}", ["100", "110"]) for index in range(3)]
    group += [sample(f"DOWN{index}", ["100", "90"]) for index in range(3)]

    assert market_candidates({"SPOT": group}, as_of=AS_OF) == ()


def test_market_candidates_need_enough_resonance() -> None:
    """同向程度不到门槛的市场不构成共振：4 涨 1 跌仍然算，但门槛调高后不算。"""

    group = [sample(f"UP{index}", ["100", "110"]) for index in range(4)]
    group.append(sample("DOWN", ["100", "90"]))

    kept = market_candidates({"SPOT": group}, as_of=AS_OF)
    dropped = market_candidates({"SPOT": group}, as_of=AS_OF, min_resonance=1.0)

    assert len(kept) == 1
    assert kept[0].evidence["resonance"] == pytest.approx(0.6)  # |4 - 1| / 5
    assert dropped == ()
    assert MIN_RESONANCE == 0.2


def test_market_candidates_are_deterministic() -> None:
    """同一份输入两次调用得到完全相同的候选（腿的顺序、分数、判定依据都一样）。"""

    group = [sample(f"S{index}", ["100", "110"]) for index in range(5)]

    first = market_candidates({"SPOT": group}, as_of=AS_OF)
    second = market_candidates({"SPOT": group}, as_of=AS_OF)

    assert first == second
    assert isinstance(first[0], Candidate)


def test_thresholds_are_the_documented_values() -> None:
    """门槛值本身就是契约的一部分：改了门槛必须同时改这条用例。"""

    assert (MIN_TREND, MIN_ABS_CORRELATION, MIN_RESONANCE) == (0.01, 0.5, 0.2)

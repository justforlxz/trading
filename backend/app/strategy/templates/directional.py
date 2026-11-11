"""方向性模板：先定方向，再从候选池挑同向最强的若干标的，全多头或全空头。

三段判断，各自有唯一的来源：

1. 方向 —— 广度与趋势共同确定：`(整组广度和 + 组内平均趋势) / 2` 的符号。广度说明
   「这一组整体在往哪边走」，平均趋势说明「组内多数标的站在自己均线的哪一侧」。
   两者抵消到正好 0 时方向未定，此时不建仓，而不是随便挑一边。
2. 候选池 —— 复合分数与方向同号，且相关性变化为正（联动性在增强）。复合分数是趋势、
   动量与广度三者的平均，三者在同一把尺子上（见 `ComponentSignal`）。
3. 配权 —— 按复合分数的绝对值分配，权重绝对值之和为 1。

相关性变化只当闸门、不参与配权：它是「会不会跟着走」的判断，不是「该给多少仓」的
判断，混进权重会让仓位数由数据可得性决定而不是由强度决定。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.indicators import Param
from app.strategy.components import Breadth, CorrelationShift, Momentum, Trend
from app.strategy.protocol import StrategyMeta
from app.strategy.registry import register_template
from app.strategy.target import TargetLeg, TargetPortfolio
from app.strategy.templates import mean
from app.strategy.view import MarketView

__all__ = ["Directional"]

_ZERO = Decimal(0)
_TWO = Decimal(2)
_THREE = Decimal(3)
_REASON = "广度 {breadth} / 趋势 {trend} / 动量 {momentum}"


def _agrees(score: Decimal, side: str) -> bool:
    """分数方向与目标方向一致；分数恰好为 0 时不算候选。"""

    return score > _ZERO if side == "long" else score < _ZERO


def side_of(market: Decimal, trends: Sequence[Decimal]) -> str | None:
    """整组方向：`(广度 + 组内平均趋势) / 2` 的符号。

    广度说「这一组整体在往哪边走」，平均趋势说「组内多数标的站在自己均线的哪一侧」。
    两者正好抵消到 0 时没有方向，返回 `None`——随便挑一边建仓比不建仓更糟。这个判断
    单独成函数，是因为「抵消到 0」在真实行情里很难凑出来，靠端到端用例覆盖不到。
    """

    score = (market + mean(trends)) / _TWO
    if score == _ZERO:
        return None
    return "long" if score > _ZERO else "short"


@dataclass(frozen=True, slots=True)
class Directional:
    """全多头或全空头的方向性组合。"""

    meta = StrategyMeta(
        name="directional",
        title="方向性组合",
        summary="广度与趋势定方向。从候选池挑同向最强的若干标的并按强度配权。",
    )
    param_schema = (
        Param("trend_window", "趋势窗口", "int", 20, 2, 500),
        Param("momentum_window", "动量窗口", "int", 10, 1, 500),
        Param("leg_count", "持仓腿数", "int", 3, 1, 50),
    )

    bar: str = "1d"
    trend_window: int = 20
    momentum_window: int = 10
    leg_count: int = 3

    def build(self, view: MarketView) -> TargetPortfolio:
        trend = Trend(bar=self.bar, window=self.trend_window).evaluate(view)
        momentum = Momentum(bar=self.bar, window=self.momentum_window).evaluate(view)
        breadth = Breadth(bar=self.bar).evaluate(view)
        confirmation = CorrelationShift(bar=self.bar).evaluate(view)

        covered = sorted(
            set(trend.scores)
            & set(momentum.scores)
            & set(breadth.scores)
            & set(confirmation.scores)
        )
        if not covered:
            return TargetPortfolio(as_of=view.as_of, legs=())

        market = mean([breadth.scores[key] for key in covered])
        side = side_of(market, [trend.scores[key] for key in covered])
        if side is None:
            return TargetPortfolio(as_of=view.as_of, legs=())

        composite = {
            key: (trend.scores[key] + momentum.scores[key] + market) / _THREE for key in covered
        }
        candidates = [
            key
            for key in covered
            if _agrees(composite[key], side) and confirmation.scores[key] > _ZERO
        ]
        if not candidates:
            return TargetPortfolio(as_of=view.as_of, legs=())

        candidates.sort(key=lambda key: (-abs(composite[key]), key))
        chosen = candidates[: self.leg_count]
        strength = sum(abs(composite[key]) for key in chosen)
        if strength == _ZERO:
            return TargetPortfolio(as_of=view.as_of, legs=())

        legs = tuple(
            TargetLeg(
                product_key=key,
                side=side,
                target_weight=abs(composite[key]) / strength,
                reason=_REASON.format(
                    breadth=market,
                    trend=trend.scores[key],
                    momentum=momentum.scores[key],
                ),
            )
            for key in sorted(chosen)
        )
        return TargetPortfolio(as_of=view.as_of, legs=legs)


register_template(Directional)

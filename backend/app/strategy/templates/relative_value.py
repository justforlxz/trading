"""相对价值模板：在高相关且偏离大的标的中配对，做多相对低估、做空相对高估。

信号各有分工：

- 相关性（`MarketView.matrix`，T2.3 交付）决定「谁和谁可以配对」：只有联动性足够高的
  两个标的，价格偏离才有均值回归的意义；不相关的两个标的的价差可以一直扩大。
- 均值回归决定「哪一边低估、哪一边高估」：分数高的一腿做多，分数低的一腿做空。
- 相对强弱决定「这对偏离值不值得看」：两腿的相对强弱差越大，说明一个是组内强手、
  一个是弱手，偏离不是噪声。

配对按 `|相关系数| × (均值回归差 + 相对强弱差)` 从大到小挑，同一个标的不进两对
（目标组合里一个产品只能有一条腿）。每对拿到相同的资金预算，腿内按偏离幅度分配，
两腿权重接近但不必相等；全部腿的权重绝对值之和为 1。

腿数与单腿权重的硬约束（单笔敞口上限、集中度等）由 T3.5 的组合生成节点在模板
输出之上求值，本模板只给「按信号应该是什么」。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.indicators import Param
from app.strategy.components import MeanReversion, RelativeStrength
from app.strategy.protocol import StrategyMeta
from app.strategy.registry import register_template
from app.strategy.target import TargetLeg, TargetPortfolio
from app.strategy.view import MarketView

__all__ = ["MIN_LEG_SHARE", "MIN_PAIR_CORRELATION", "RelativeValue"]

_ZERO = Decimal(0)
_TWO = Decimal(2)
_ONE = Decimal(1)

# 配对的相关性门槛：低于它的两个标的在统计上不构成「同一对」,价差回归没有依据。
MIN_PAIR_CORRELATION = 0.3

# 单腿在该对预算里的最小占比。正文要求「两腿权重接近但不必相等」：按偏离幅度原样
# 分配时，一侧偏离 0.5、另一侧 0.02 会得到 0.96 / 0.04，那样的「对冲」实际是单边
# 持仓，波动风险没有被对冲掉。把它夹在 [0.4, 0.6] 既保留强弱差异，又保证两腿同量级。
MIN_LEG_SHARE = Decimal("0.4")

_REASON = "与 {partner} 相关 {correlation:.2f} / 均值回归 {reversion} / 相对强弱 {strength}"


@dataclass(frozen=True, slots=True)
class RelativeValue:
    """多空并存的对冲组合，净敞口可接近 0。"""

    meta = StrategyMeta(
        name="relative_value",
        title="相对价值组合",
        summary="在高相关且偏离大的标的中配对。做多相对低估、做空相对高估。",
    )
    param_schema = (
        Param("reversion_window", "均值回归窗口", "int", 20, 2, 500),
        Param("strength_window", "相对强弱窗口", "int", 10, 1, 500),
        Param("pair_count", "配对数量", "int", 1, 1, 20),
    )

    bar: str = "1d"
    reversion_window: int = 20
    strength_window: int = 10
    pair_count: int = 1

    def build(self, view: MarketView) -> TargetPortfolio:
        reversion = MeanReversion(bar=self.bar, window=self.reversion_window).evaluate(view)
        strength = RelativeStrength(bar=self.bar, window=self.strength_window).evaluate(view)

        paired = set(view.matrix.symbols)
        covered = sorted(set(reversion.scores) & set(strength.scores) & paired)
        if len(covered) < 2:
            return TargetPortfolio(as_of=view.as_of, legs=())

        ranked: list[tuple[Decimal, str, str]] = []
        for position, left in enumerate(covered):
            for right in covered[position + 1 :]:
                coefficient = view.matrix[left].get(right)
                if coefficient is None or abs(coefficient) < MIN_PAIR_CORRELATION:
                    continue
                divergence = abs(reversion.scores[left] - reversion.scores[right]) + abs(
                    strength.scores[left] - strength.scores[right]
                )
                if divergence == _ZERO:
                    continue
                ranked.append((Decimal(str(abs(coefficient))) * divergence, left, right))
        ranked.sort(key=lambda item: (-item[0], item[1], item[2]))

        taken: set[str] = set()
        pairs: list[tuple[str, str]] = []
        for _, left, right in ranked:
            if len(pairs) == self.pair_count:
                break
            if left in taken or right in taken:
                continue
            taken.update({left, right})
            pairs.append((left, right))
        if not pairs:
            return TargetPortfolio(as_of=view.as_of, legs=())

        budget = _ONE / Decimal(len(pairs))
        legs: list[TargetLeg] = []
        for left, right in pairs:
            cheap, rich = sorted(
                (left, right), key=lambda key: (reversion.scores[key], key), reverse=True
            )
            cheap_size = abs(reversion.scores[cheap])
            rich_size = abs(reversion.scores[rich])
            if cheap_size + rich_size == _ZERO:
                long_weight = budget / _TWO
            else:
                share = cheap_size / (cheap_size + rich_size)
                long_weight = budget * min(max(share, MIN_LEG_SHARE), _ONE - MIN_LEG_SHARE)
            coefficient = view.matrix[cheap][rich]
            assert coefficient is not None  # 门槛已排除无系数的配对
            legs.append(
                TargetLeg(
                    product_key=cheap,
                    side="long",
                    target_weight=long_weight,
                    reason=_REASON.format(
                        partner=rich,
                        correlation=coefficient,
                        reversion=reversion.scores[cheap],
                        strength=strength.scores[cheap],
                    ),
                )
            )
            legs.append(
                TargetLeg(
                    product_key=rich,
                    side="short",
                    target_weight=budget - long_weight,
                    reason=_REASON.format(
                        partner=cheap,
                        correlation=coefficient,
                        reversion=reversion.scores[rich],
                        strength=strength.scores[rich],
                    ),
                )
            )

        legs.sort(key=lambda leg: leg.product_key)
        return TargetPortfolio(as_of=view.as_of, legs=tuple(legs))


register_template(RelativeValue)

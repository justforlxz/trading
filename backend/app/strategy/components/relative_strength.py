"""相对强弱组件：同一组产品内部的相对收益。

与动量组件的区别在这里：动量问「这个标的涨了多少」，相对强弱问「它比同组其他标的
强多少」。后者减去全组的中位数收益，因此整组普涨或普跌都不会让它集体给正分——
那正是组合层要区分的东西：普涨时挑最弱的做空没有意义，挑相对最强的才有多空价值。

中位数而不是平均值：一个标的暴涨不会把同组其余标的都判成「跑输」。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.core import InvariantViolation
from app.strategy.components import check_window, closes, simple_return, squash
from app.strategy.protocol import ComponentSignal
from app.strategy.registry import register_component
from app.strategy.view import MarketView

__all__ = ["RelativeStrength", "median"]

_TWO = Decimal(2)


def median(values: Sequence[Decimal]) -> Decimal:
    """中位数：奇数取正中，偶数取中间两个的均值。空序列没有中位数，直接报错。"""

    if not values:
        raise InvariantViolation("空序列没有中位数")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / _TWO


@dataclass(frozen=True, slots=True)
class RelativeStrength:
    """各标的 `window` 根收益率减去全组中位数，再压到 `[-1, 1]`。"""

    name = "relative_strength"

    bar: str = "1d"
    window: int = 10

    def __post_init__(self) -> None:
        check_window(self.window)

    def evaluate(self, view: MarketView) -> ComponentSignal:
        changes: dict[str, Decimal] = {}
        for product_key, bars in view.bars(view.product_keys, self.bar).items():
            change = simple_return(closes(bars), self.window)
            if change is not None:
                changes[product_key] = change
        if not changes:
            return ComponentSignal(name=self.name, as_of=view.as_of, scores={})

        middle = median(list(changes.values()))
        scores = {key: squash(change - middle) for key, change in changes.items()}
        return ComponentSignal(name=self.name, as_of=view.as_of, scores=scores)


register_component(RelativeStrength)

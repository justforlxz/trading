"""均值回归组件：价格相对自身均线的偏离，方向与趋势相反。

与趋势跟踪用的是同一个偏离量，但符号相反：价格高于均线时认为「偏贵」（负分），
低于均线时认为「偏便宜」（正分）。两者不合并成一个组件，因为它们在同一个模板里
可能同时出现，符号相反正是相对价值策略要的信息。

偏离用比例而不是绝对价差，不同价位的标的才能放在同一把尺子上比较。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.strategy.components import check_window, closes, squash
from app.strategy.protocol import ComponentSignal
from app.strategy.registry import register_component
from app.strategy.view import MarketView

__all__ = ["MeanReversion"]

_ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class MeanReversion:
    """`(均线 - 收盘价) / 均线`：低于均线给正分（偏便宜），高于均线给负分。"""

    name = "mean_reversion"

    bar: str = "1d"
    window: int = 20

    def __post_init__(self) -> None:
        check_window(self.window)

    def evaluate(self, view: MarketView) -> ComponentSignal:
        scores: dict[str, Decimal] = {}
        for product_key, bars in view.bars(view.product_keys, self.bar).items():
            values = closes(bars)
            if len(values) < self.window:
                continue
            average = sum(values[-self.window :]) / Decimal(self.window)
            if average == _ZERO:
                continue
            scores[product_key] = squash((average - values[-1]) / average)
        return ComponentSignal(name=self.name, as_of=view.as_of, scores=scores)


register_component(MeanReversion)

"""动量组件：最近一段时间的累计涨跌幅。

与趋势跟踪的分工：趋势看「价格相对均线的位置」，动量看「这段时间涨了多少」。
两者会给出相反的读数（长期上行但最近回调），这正是它们各自独立的价值。

区间是最近 `window` 根收盘价的单期收益率，不年化、不扣成本：这一层只判断方向与
强度，成本由回测的成本模型处理。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.strategy.components import check_window, closes, simple_return, squash
from app.strategy.protocol import ComponentSignal
from app.strategy.registry import register_component
from app.strategy.view import MarketView

__all__ = ["Momentum"]


@dataclass(frozen=True, slots=True)
class Momentum:
    """`window` 根内的累计收益率，再压到 `[-1, 1]`。"""

    name = "momentum"

    bar: str = "1d"
    window: int = 10

    def __post_init__(self) -> None:
        check_window(self.window)

    def evaluate(self, view: MarketView) -> ComponentSignal:
        scores: dict[str, Decimal] = {}
        for product_key, bars in view.bars(view.product_keys, self.bar).items():
            change = simple_return(closes(bars), self.window)
            if change is None:
                continue
            scores[product_key] = squash(change)
        return ComponentSignal(name=self.name, as_of=view.as_of, scores=scores)


register_component(Momentum)

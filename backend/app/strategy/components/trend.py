"""趋势跟踪组件：收盘价相对自身均线的位置。

判断只有一条：价格站在均线上方算多头倾向，站在下方算空头倾向，离得越远强度越大。
均线用收盘价的算术平均，与 `app.indicators` 的 SMA 是同一个定义，但这里只要最后
一个值，不必为整个序列建 `Series`。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.strategy.components import check_window, closes, squash
from app.strategy.protocol import ComponentSignal
from app.strategy.registry import register_component
from app.strategy.view import MarketView

__all__ = ["Trend"]

_ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class Trend:
    """均线偏离度：`(收盘价 - 均线) / 均线`，再压到 `[-1, 1]`。"""

    name = "trend"

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
            scores[product_key] = squash(values[-1] / average - Decimal(1))
        return ComponentSignal(name=self.name, as_of=view.as_of, scores=scores)


register_component(Trend)

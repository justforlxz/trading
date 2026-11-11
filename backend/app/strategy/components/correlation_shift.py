"""相关性变化组件：这个标的与整组的联动性在增强还是减弱。

用「最近一段窗口的相关系数」减「前一段窗口的相关系数」：为正说明它与整组越来越同步，
为负说明它在脱钩。模板把它当方向确认——整组方向已经由广度与趋势定下来之后，只有
联动性正在增强的标的才算「会跟着走」，脱钩的标的不进候选池。

整组序列取横截面的平均收益：这是一个「组」的概念，不是第二个行情源，因此不需要
额外的矩阵输入。相关系数用 `app.market.pearson`（T2.3 已交付），不在这里重写一份。

相关系数是浮点量：它是无量纲的统计量，与金额、价格无关，不存在十进制精度约定；
分数在出口处转回 `Decimal`，与其余组件的口径一致。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.core import Bar, ValidationError
from app.market import pearson
from app.strategy.components import check_window, squash
from app.strategy.protocol import ComponentSignal
from app.strategy.registry import register_component
from app.strategy.view import MarketView

__all__ = ["CorrelationShift"]

_ONE = Decimal(1)
# `pearson` 需要至少 3 个样本才能给出系数，窗口再小就永远算不出来。
_MIN_WINDOW = 3


def _usable_moments(bars: Sequence[Bar]) -> set[datetime]:
    """能算出收益率的时刻：不是第一根，且前一根收盘价不是 0。"""

    return {
        bar.open_time
        for position, bar in enumerate(bars)
        if position > 0 and bars[position - 1].close != 0
    }


def _changes(bars: Sequence[Bar], moments: Sequence[datetime]) -> dict[datetime, Decimal]:
    """只给用得到的时刻算收益率。

    整段历史逐根做十进制除法在长周期视图上不划算（`1m` 可达几十万根），而这里只用到
    最后 `2 * window` 个时刻。不能简单地把 K 线切到 `bars[-(2 * window + 1):]`：不同
    标的的历史长度不同，各自切尾后的交集可能落在不同时间段，反而把本来够用的共同历史
    切没了。因此先求交集、再只对这些时刻求值。
    """

    positions = {bar.open_time: index for index, bar in enumerate(bars)}
    changes: dict[datetime, Decimal] = {}
    for moment in moments:
        index = positions[moment]
        changes[moment] = bars[index].close / bars[index - 1].close - _ONE
    return changes


@dataclass(frozen=True, slots=True)
class CorrelationShift:
    """两个相邻窗口的相关系数之差，再压到 `[-1, 1]`。"""

    name = "correlation_shift"

    bar: str = "1d"
    window: int = 20

    def __post_init__(self) -> None:
        if check_window(self.window) < _MIN_WINDOW:
            raise ValidationError(f"相关性变化的窗口至少 {_MIN_WINDOW} 根, 实际 {self.window}")

    def evaluate(self, view: MarketView) -> ComponentSignal:
        bars_by_product = view.bars(view.product_keys, self.bar)
        if not bars_by_product:
            return ComponentSignal(name=self.name, as_of=view.as_of, scores={})

        # 只在所有标的都能算出收益率的时刻上比较：组序列是这些时刻的横截面平均，
        # 缺一个标的的时刻会让「整组」少一个成员，两份窗口的成员就不可比了。
        usable = {
            product_key: _usable_moments(bars) for product_key, bars in bars_by_product.items()
        }
        common = sorted(set.intersection(*usable.values()))
        if len(common) < self.window * 2:
            return ComponentSignal(name=self.name, as_of=view.as_of, scores={})

        recent = common[-self.window :]
        previous = common[-self.window * 2 : -self.window]
        needed = previous + recent

        changes_by_product = {
            product_key: _changes(bars, needed) for product_key, bars in bars_by_product.items()
        }
        grouped = {
            moment: sum(changes[moment] for changes in changes_by_product.values())
            / Decimal(len(changes_by_product))
            for moment in needed
        }

        scores: dict[str, Decimal] = {}
        for product_key, changes in changes_by_product.items():
            now = pearson(
                [float(changes[moment]) for moment in recent],
                [float(grouped[moment]) for moment in recent],
            )
            before = pearson(
                [float(changes[moment]) for moment in previous],
                [float(grouped[moment]) for moment in previous],
            )
            if now is None or before is None:
                continue
            scores[product_key] = squash(Decimal(str(now - before)))
        return ComponentSignal(name=self.name, as_of=view.as_of, scores=scores)


register_component(CorrelationShift)

"""广度组件：一组产品的涨跌家数差，给出整组的共同方向。

这是唯一一个「整组给同一个分数」的组件：它回答的不是「哪个标的强」，而是「这一组
现在整体在往哪边动」。模板用它定方向，再用趋势、动量在组内挑标的。

涨跌家数取自 `app.market.advance_decline`（T2.5 已交付），不在这里重写一份；T2.5
的约定是入参只含同一资产类别的一组序列，类别由装配层分组，本组件不跨类别混算。

整组不足两根 K 线时没有方向可判断，`scores` 为空：补一个 0 会被当成「多空平衡」，
而「样本不足」与「多空平衡」不是一回事。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.market import advance_decline
from app.strategy.protocol import ComponentSignal
from app.strategy.registry import register_component
from app.strategy.view import MarketView

__all__ = ["Breadth"]


@dataclass(frozen=True, slots=True)
class Breadth:
    """`(上涨家数 - 下跌家数) / 参与家数`，恒在 `[-1, 1]`，整组同值。"""

    name = "breadth"

    bar: str = "1d"

    def evaluate(self, view: MarketView) -> ComponentSignal:
        bars = view.bars(view.product_keys, self.bar)
        counted = advance_decline(bars)
        if counted.participants == 0:
            return ComponentSignal(name=self.name, as_of=view.as_of, scores={})

        score = Decimal(counted.advancers - counted.decliners) / Decimal(counted.participants)
        return ComponentSignal(
            name=self.name,
            as_of=view.as_of,
            # 不足两根 K 线的产品没有方向，`advance_decline` 也没把它计入参与者；
            # 给它一个整组读数等于凭空造一个判断，与「判断不出来就不出读数」相悖。
            scores={
                product_key: score
                for product_key, bars_of_product in bars.items()
                if len(bars_of_product) >= 2
            },
        )


register_component(Breadth)

"""旧式策略的用例：四个经典单指标策略降级为组件的用法示例。

它们**不是**组合模板：模板只有方向性与相对价值两类。这四个类保留下来是为了证明
「原来的单指标策略现在由哪个组件表达」，并让 `get_strategy` 仍能按名字取到它们；
它们不出现在 `list_templates()` 里。

对应关系：

| 用例 | 组件 | 说明 |
| --- | --- | --- |
| 均线交叉 | 趋势跟踪 | 价格站在均线上方做多、下方做空 |
| 动量 | 动量 | 最近一段时间的累计涨跌幅方向 |
| RSI 反转 | 均值回归 | 短期偏离视为超买超卖 |
| 布林带反转 | 均值回归 | 偏离滚动中枢的幅度视为高估低估 |

RSI 与布林带都落到均值回归组件：两者量的都是「价格离滚动参考有多远」，只是参考
窗口不同（14 根与 20 根），没有必要各写一个组件。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.strategy.components import MeanReversion, Momentum, Trend
from app.strategy.protocol import ComponentSignal, Requirements, StrategyMeta
from app.strategy.registry import register_strategy
from app.strategy.target import TargetLeg, TargetPortfolio
from app.strategy.view import MarketView

__all__ = ["BollingerReversion", "MaCross", "MacdMomentum", "RsiReversal"]

_BAR = "1d"
_ONE = Decimal(1)


def _equal_weight(view: MarketView, signal: ComponentSignal) -> TargetPortfolio:
    """把组件分数翻成「同向等权」的目标组合：分数为 0 的产品不建仓。"""

    sides = {
        product_key: "long" if score > 0 else "short"
        for product_key, score in signal.scores.items()
        if score != 0
    }
    if not sides:
        return TargetPortfolio(as_of=view.as_of, legs=())

    weight = _ONE / Decimal(len(sides))
    legs = tuple(
        TargetLeg(product_key=key, side=side, target_weight=weight, reason=signal.name)
        for key, side in sorted(sides.items())
    )
    return TargetPortfolio(as_of=view.as_of, legs=legs)


@dataclass(frozen=True, slots=True)
class MaCross:
    """均线交叉：趋势跟踪组件的用例。"""

    meta = StrategyMeta(
        name="ma_cross",
        title="均线交叉",
        summary="价格站在均线上方做多、下方做空。同向等权。",
    )
    param_schema = ()
    requires = Requirements(bar=_BAR, lookback=20)

    def evaluate(self, view: MarketView) -> TargetPortfolio:
        return _equal_weight(view, Trend(bar=_BAR, window=self.requires.lookback).evaluate(view))


@dataclass(frozen=True, slots=True)
class MacdMomentum:
    """动量：动量组件的用例。"""

    meta = StrategyMeta(
        name="macd_momentum",
        title="动量",
        summary="最近一段时间的累计涨跌幅定方向。同向等权。",
    )
    param_schema = ()
    requires = Requirements(bar=_BAR, lookback=10)

    def evaluate(self, view: MarketView) -> TargetPortfolio:
        return _equal_weight(view, Momentum(bar=_BAR, window=self.requires.lookback).evaluate(view))


@dataclass(frozen=True, slots=True)
class RsiReversal:
    """短期偏离反转：均值回归组件的用例（14 根窗口）。"""

    meta = StrategyMeta(
        name="rsi_reversal",
        title="RSI 反转",
        summary="短期偏离滚动中枢视为超买超卖。同向等权。",
    )
    param_schema = ()
    requires = Requirements(bar=_BAR, lookback=14)

    def evaluate(self, view: MarketView) -> TargetPortfolio:
        return _equal_weight(
            view, MeanReversion(bar=_BAR, window=self.requires.lookback).evaluate(view)
        )


@dataclass(frozen=True, slots=True)
class BollingerReversion:
    """偏离滚动中枢：均值回归组件的用例（20 根窗口）。"""

    meta = StrategyMeta(
        name="bollinger_reversion",
        title="布林带反转",
        summary="偏离滚动中枢的幅度视为高估低估。同向等权。",
    )
    param_schema = ()
    requires = Requirements(bar=_BAR, lookback=20)

    def evaluate(self, view: MarketView) -> TargetPortfolio:
        return _equal_weight(
            view, MeanReversion(bar=_BAR, window=self.requires.lookback).evaluate(view)
        )


register_strategy(MaCross)
register_strategy(MacdMomentum)
register_strategy(RsiReversal)
register_strategy(BollingerReversion)

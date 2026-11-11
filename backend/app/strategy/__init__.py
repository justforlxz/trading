"""策略域：目标组合、只读行情视图、策略协议、注册表与参数校验。

本域对外只发布一种交易目标：`TargetPortfolio`（多腿、方向、目标权重）。策略不产出
单标的的动作序列，也不接触交易所、账户与会话。

跨包调用一律走本门面，不允许 `from app.strategy.target import ...` 之类的子模块直连。
"""

from app.strategy.params import resolve_params
from app.strategy.protocol import Requirements, Strategy, StrategyMeta
from app.strategy.registry import get_strategy, list_strategies, register_strategy
from app.strategy.target import TargetLeg, TargetPortfolio
from app.strategy.view import MarketView

__all__ = [
    "MarketView",
    "Requirements",
    "Strategy",
    "StrategyMeta",
    "TargetLeg",
    "TargetPortfolio",
    "get_strategy",
    "list_strategies",
    "register_strategy",
    "resolve_params",
]

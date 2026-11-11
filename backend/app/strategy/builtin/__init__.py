"""旧式策略的用例包：经典单指标策略降级为组件用法的示例，不是组合模板。"""

from app.strategy.builtin.classic import (
    BollingerReversion,
    MacdMomentum,
    MaCross,
    RsiReversal,
)

__all__ = ["BollingerReversion", "MaCross", "MacdMomentum", "RsiReversal"]

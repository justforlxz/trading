"""回测域：成本模型与绩效指标。

本节点只提供纯函数，撮合与组合构建在后续节点接入。跨包调用一律走本门面。
"""

from app.backtest.costs import CostModel, execution_prices, fee_cost, slippage_cost
from app.backtest.metrics import METRIC_NAMES, compute_metrics, default_annualization_factor

__all__ = [
    "METRIC_NAMES",
    "CostModel",
    "compute_metrics",
    "default_annualization_factor",
    "execution_prices",
    "fee_cost",
    "slippage_cost",
]

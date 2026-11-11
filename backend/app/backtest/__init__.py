"""回测域：成本模型、绩效指标、撮合调仓与组合级 bar 循环。

本域只做计算，不碰交易所、数据库与会话。跨包调用一律走本门面。

- `costs`：手续费与滑点；
- `metrics`：绩效指标；
- `simulation`：把目标组合与当前持仓的差额换成增量订单再换成成交；
- `engine`：按目标组合序列推进 bar 循环，产出净值曲线与逐腿成交。
"""

from app.backtest.costs import (
    CostModel,
    execution_price,
    execution_prices,
    fee_cost,
    slippage_cost,
)
from app.backtest.engine import BacktestInput, BacktestResult, EquityPoint, run_backtest
from app.backtest.errors import BacktestError, BarSeriesError, MissingInstrumentError
from app.backtest.metrics import METRIC_NAMES, compute_metrics, default_annualization_factor
from app.backtest.simulation import (
    ExecutionResult,
    LegCost,
    LegExit,
    LegFill,
    LegOrder,
    LegPosition,
    Settlement,
    execute_orders,
    plan_orders,
    resolve_exit,
)

__all__ = [
    "METRIC_NAMES",
    "BacktestError",
    "BacktestInput",
    "BacktestResult",
    "BarSeriesError",
    "CostModel",
    "EquityPoint",
    "ExecutionResult",
    "LegCost",
    "LegExit",
    "LegFill",
    "LegOrder",
    "LegPosition",
    "MissingInstrumentError",
    "Settlement",
    "compute_metrics",
    "default_annualization_factor",
    "execute_orders",
    "execution_price",
    "execution_prices",
    "fee_cost",
    "plan_orders",
    "resolve_exit",
    "run_backtest",
    "slippage_cost",
]

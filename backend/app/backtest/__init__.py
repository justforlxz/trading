"""回测域：成本模型、绩效指标、撮合调仓、组合级 bar 循环与结果持久化。

跨包调用一律走本门面。

- `costs`：手续费与滑点；
- `metrics`：绩效指标、逐腿完整交易与组合级口径；
- `simulation`：把目标组合与当前持仓的差额换成增量订单再换成成交；
- `engine`：按目标组合序列推进 bar 循环，产出净值曲线与逐腿成交；
- `margin`：逐仓保证金、杠杆档位与强平价；
- `funding_cost`：按 8 小时结算点把资金费计入 PnL，并报告覆盖率缺口；
- `model` / `service`：把一次回测落库并读回（含逐腿交易与逐 bar 净敞口）；
- `batch`：批量结果的排序与交易次数过滤（只排序，不标「最优」）；
- `sweep`：参数笛卡尔积、训练/验证/样本外三段切分与扫描行。
"""

from app.backtest.batch import rank_rows
from app.backtest.costs import (
    CostModel,
    execution_price,
    execution_prices,
    fee_cost,
    slippage_cost,
)
from app.backtest.engine import (
    BacktestInput,
    BacktestResult,
    EquityPoint,
    MarginPoint,
    run_backtest,
)
from app.backtest.errors import BacktestError, BarSeriesError, MissingInstrumentError
from app.backtest.funding_cost import (
    FundingSettlement,
    funding_points_between,
    on_funding_grid,
)
from app.backtest.margin import (
    DEFAULT_MAX_LEVERAGE,
    HARD_MAX_LEVERAGE,
    MarginTerms,
    PositionTier,
    effective_leverage,
    initial_margin,
    liquidated_in_bar,
    liquidation_price,
    maintenance_margin,
    margin_terms,
    margin_used,
    max_loss,
    parse_position_tiers,
    tier_for,
)
from app.backtest.metrics import (
    METRIC_NAMES,
    ClosedTrade,
    ExposurePoint,
    closed_trades,
    compute_metrics,
    default_annualization_factor,
    exposure_series,
    portfolio_metrics,
)
from app.backtest.model import BacktestEquityRow, BacktestRunRow, BacktestTradeRow
from app.backtest.service import (
    BacktestRunHeader,
    BacktestRunPlan,
    BacktestRunRecord,
    BacktestSpec,
    data_fingerprint,
    delete_run,
    get_run,
    latest_linked_backtests,
    latest_run,
    list_instrument_runs,
    list_runs,
    save_run,
    save_runs,
)
from app.backtest.settlement import AccountSettlement
from app.backtest.simulation import (
    ExecutionResult,
    FundingReport,
    LegCost,
    LegExit,
    LegFill,
    LegLiquidation,
    LegOrder,
    LegPosition,
    Settlement,
    SettlementOutcome,
    execute_orders,
    plan_orders,
    resolve_exit,
)
from app.backtest.sweep import (
    SplitWindow,
    SweepCell,
    SweepRow,
    param_combinations,
    rank_sweep,
    split_window,
    validate_splits,
)

__all__ = [
    "DEFAULT_MAX_LEVERAGE",
    "HARD_MAX_LEVERAGE",
    "METRIC_NAMES",
    "AccountSettlement",
    "BacktestEquityRow",
    "BacktestError",
    "BacktestInput",
    "BacktestResult",
    "BacktestRunHeader",
    "BacktestRunPlan",
    "BacktestRunRecord",
    "BacktestRunRow",
    "BacktestSpec",
    "BacktestTradeRow",
    "BarSeriesError",
    "ClosedTrade",
    "CostModel",
    "EquityPoint",
    "ExecutionResult",
    "ExposurePoint",
    "FundingReport",
    "FundingSettlement",
    "LegCost",
    "LegExit",
    "LegFill",
    "LegLiquidation",
    "LegOrder",
    "LegPosition",
    "MarginPoint",
    "MarginTerms",
    "MissingInstrumentError",
    "PositionTier",
    "Settlement",
    "SettlementOutcome",
    "SplitWindow",
    "SweepCell",
    "SweepRow",
    "closed_trades",
    "compute_metrics",
    "data_fingerprint",
    "default_annualization_factor",
    "delete_run",
    "effective_leverage",
    "execute_orders",
    "execution_price",
    "execution_prices",
    "exposure_series",
    "fee_cost",
    "funding_points_between",
    "get_run",
    "initial_margin",
    "latest_linked_backtests",
    "latest_run",
    "liquidated_in_bar",
    "liquidation_price",
    "list_instrument_runs",
    "list_runs",
    "maintenance_margin",
    "margin_terms",
    "margin_used",
    "max_loss",
    "on_funding_grid",
    "param_combinations",
    "parse_position_tiers",
    "plan_orders",
    "portfolio_metrics",
    "rank_rows",
    "rank_sweep",
    "resolve_exit",
    "run_backtest",
    "save_run",
    "save_runs",
    "slippage_cost",
    "split_window",
    "tier_for",
    "validate_splits",
]

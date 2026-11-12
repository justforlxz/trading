"""回测契约：请求配置、运行结果、排名、参数扫描。

数据源（`data_source`）是一等参数：代理数据与 OKX 实盘标的分开存放与排序，
列表/排名接口必须显式带数据源，禁止跨源聚合（见 decisions.md D3）。
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import (
    Bar,
    DataSource,
    DecimalString,
    ExecutionModel,
    InstType,
    ParamValue,
    PositionSide,
    UtcDatetime,
)

__all__ = [
    "BacktestCosts",
    "BacktestDetailResponse",
    "BacktestLeg",
    "BacktestMetrics",
    "BacktestPortfolio",
    "BacktestRankingResponse",
    "BacktestRankingRow",
    "BacktestRequest",
    "BacktestRunListResponse",
    "BacktestRunSummary",
    "BacktestSweepCombo",
    "BacktestSweepRequest",
    "BacktestSweepResponse",
    "BacktestTargets",
    "BacktestTrade",
    "EquityPoint",
    "RankingMetric",
    "RunStatus",
    "TimeSplit",
]

RunStatus = Literal["queued", "running", "succeeded", "failed"]
RankingMetric = Literal["total_return_pct", "max_drawdown_pct", "sharpe", "profit_factor"]


class BacktestTargets(BaseModel):
    """标的范围：单标的 / 手选多个 / 自选分组 / Watchlist 全部 / 全市场。"""

    mode: Literal["single", "list", "watchlist", "group", "all"]
    inst_ids: list[str] = Field(default_factory=list)
    group: str | None = None


class BacktestCosts(BaseModel):
    maker_fee_bps: DecimalString
    taker_fee_bps: DecimalString
    slippage_bps: DecimalString
    spread_bps: DecimalString


class BacktestRequest(BaseModel):
    """一次回测的全部可复现输入。结果必须能按这份配置重放。"""

    strategy_instance_id: str
    targets: BacktestTargets
    bar: Bar
    start_date: date
    end_date: date
    initial_capital: DecimalString
    quote_currency: str
    position_size: DecimalString
    max_position_pct: DecimalString
    costs: BacktestCosts
    # 永续资金费默认开启；关闭需显式传 false，且随结果落库（decisions.md D2）。
    funding_enabled: bool = True
    execution_model: ExecutionModel
    data_source: DataSource


class BacktestMetrics(BaseModel):
    initial_capital: DecimalString
    final_capital: DecimalString
    total_return_pct: DecimalString
    annualized_return_pct: DecimalString | None = None
    max_drawdown_pct: DecimalString
    win_rate: DecimalString
    payoff_ratio: DecimalString
    profit_factor: DecimalString
    sharpe: DecimalString
    trade_count: int
    avg_holding_hours: DecimalString
    max_single_win: DecimalString
    max_single_loss: DecimalString
    # 仅永续：缺失与真 0 必须可区分，覆盖率不足时前端显式标注。
    funding_total: DecimalString | None = None
    funding_coverage_pct: DecimalString | None = None
    funding_missing_count: int | None = None


_EXAMPLE_METRICS = {
    "initial_capital": "10000",
    "final_capital": "11240.55",
    "total_return_pct": "12.4055",
    "annualized_return_pct": "48.21",
    "max_drawdown_pct": "-6.12",
    "win_rate": "0.54",
    "payoff_ratio": "1.72",
    "profit_factor": "1.95",
    "sharpe": "1.31",
    "trade_count": 37,
    "avg_holding_hours": "18.4",
    "max_single_win": "312.40",
    "max_single_loss": "-158.20",
    "funding_total": "-12.84",
    "funding_coverage_pct": "100",
    "funding_missing_count": 0,
}

_EXAMPLE_RUN = {
    "run_id": "bt_0001",
    "status": "succeeded",
    "strategy_instance_id": "si_0001",
    "params": {"reversion_window": 3, "strength_window": 2, "pair_count": 1},
    "data_source": "okx",
    "inst_id": "XAAPL-USDT",
    "inst_type": "SPOT",
    "is_proxy": False,
    "bar": "1h",
    "start_date": "2026-08-01",
    "end_date": "2026-11-01",
    "symbol_count": 1,
    "created_at": "2026-11-10T01:20:00Z",
    "finished_at": "2026-11-10T01:21:30Z",
    "metrics": _EXAMPLE_METRICS,
    "error_message": None,
}

_EXAMPLE_REQUEST = {
    "strategy_instance_id": "si_0001",
    "targets": {"mode": "single", "inst_ids": ["XAAPL-USDT"], "group": None},
    "bar": "1h",
    "start_date": "2026-08-01",
    "end_date": "2026-11-01",
    "initial_capital": "10000",
    "quote_currency": "USDT",
    "position_size": "2000",
    "max_position_pct": "0.25",
    "costs": {
        "maker_fee_bps": "2",
        "taker_fee_bps": "5",
        "slippage_bps": "3",
        "spread_bps": "2",
    },
    "funding_enabled": True,
    "execution_model": "next_open",
    "data_source": "okx",
}


class BacktestRunSummary(BaseModel):
    run_id: str
    status: RunStatus
    strategy_instance_id: str
    # 这次运行实际使用的策略参数：换参数重跑会得到新的一条，列表靠它区分不同组合。
    params: dict[str, ParamValue]
    data_source: DataSource
    # 一次回测只跑一个标的：批量回测按标的分成多条运行，列表与排行榜才有一行可比。
    inst_id: str
    inst_type: InstType
    is_proxy: bool
    bar: Bar
    start_date: date
    end_date: date
    symbol_count: int
    created_at: UtcDatetime
    finished_at: UtcDatetime | None = None
    metrics: BacktestMetrics | None = None
    error_message: str | None = None

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_RUN]})


class BacktestRunListResponse(BaseModel):
    data_source: DataSource
    items: list[BacktestRunSummary]
    total: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"data_source": "okx", "items": [_EXAMPLE_RUN], "total": 1}]
        }
    )


class BacktestTrade(BaseModel):
    trade_id: str
    # `product_key` 是同一产品两种形态的配对键，界面按它把现货与永续放在一起看。
    product_key: str
    inst_id: str
    inst_type: InstType
    # 方向是持仓方向（多/空），不是单笔委托的买卖方向：一笔完整交易说的是「这条腿
    # 在多头上赚了多少」，不是「下了买单还是卖单」。
    side: PositionSide
    qty: DecimalString
    entry_time: UtcDatetime
    entry_price: DecimalString
    exit_time: UtcDatetime
    exit_price: DecimalString
    fee: DecimalString
    # 资金费按组合记账（`BacktestMetrics.funding_total`），逐腿拆分由 T4.7 承接；
    # 在那之前这里一律为 null，不用 `0` 假装「这条腿没有资金费」。
    funding: DecimalString | None = None
    pnl: DecimalString
    reason: str


class EquityPoint(BaseModel):
    time: UtcDatetime
    equity: DecimalString


class BacktestPortfolio(BaseModel):
    """组合级汇总：净敞口、每腿胜率、多腿与空腿的合计盈亏。

    逐腿明细在 `BacktestDetailResponse.legs`：这里只回答「整个组合怎么样」，
    单条腿各自赚了多少放在下面那张表里。
    """

    net_exposure: DecimalString
    leg_win_rate: dict[str, DecimalString]
    long_pnl: DecimalString
    short_pnl: DecimalString


class BacktestLeg(BaseModel):
    """一条腿在本次回测里的汇总：方向、第一笔开仓到最后一笔平仓、成本与贡献。

    `contribution_pct` 是这条腿的**已实现**盈亏占初始资金的百分比。回测结束时仍未
    平掉的仓位只体现在资金曲线里，不在逐腿明细里，因此全部腿的贡献相加可能小于总收益率
    ——差的正是未平仓部分的浮动盈亏。
    """

    product_key: str
    inst_id: str
    inst_type: InstType
    side: PositionSide
    trade_count: int
    entry_time: UtcDatetime
    exit_time: UtcDatetime
    fee: DecimalString
    funding: DecimalString | None = None
    pnl: DecimalString
    contribution_pct: DecimalString


class BacktestDetailResponse(BaseModel):
    """一次回测的完整结果：组合级汇总在上，逐腿明细在下。

    `trades` 是逐笔成交（每笔完整交易的开平仓时刻、价格、成本与盈亏），`legs` 是按
    `product_key` 与方向汇总后的逐腿明细，`equity_curve` 是逐 bar 的资金曲线。
    """

    run: BacktestRunSummary
    request: BacktestRequest
    portfolio: BacktestPortfolio
    legs: list[BacktestLeg]
    trades: list[BacktestTrade]
    equity_curve: list[EquityPoint]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "run": _EXAMPLE_RUN,
                    "request": _EXAMPLE_REQUEST,
                    "portfolio": {
                        "net_exposure": "0.5",
                        "leg_win_rate": {"XAAPL": "0.54"},
                        "long_pnl": "210.45",
                        "short_pnl": "-18.20",
                    },
                    "legs": [
                        {
                            "product_key": "XAAPL",
                            "inst_id": "XAAPL-USDT",
                            "inst_type": "SPOT",
                            "side": "long",
                            "trade_count": 37,
                            "entry_time": "2026-08-04T14:00:00Z",
                            "exit_time": "2026-10-28T06:00:00Z",
                            "fee": "18.40",
                            "funding": None,
                            "pnl": "240.55",
                            "contribution_pct": "2.4055",
                        }
                    ],
                    "trades": [
                        {
                            "trade_id": "tr_0001",
                            "product_key": "XAAPL",
                            "inst_id": "XAAPL-USDT",
                            "inst_type": "SPOT",
                            "side": "long",
                            "qty": "8.63",
                            "entry_time": "2026-08-04T14:00:00Z",
                            "entry_price": "228.10",
                            "exit_time": "2026-08-05T06:00:00Z",
                            "exit_price": "232.44",
                            "fee": "1.98",
                            "funding": None,
                            "pnl": "35.24",
                            "reason": "MA20 下穿 MA60",
                        }
                    ],
                    "equity_curve": [
                        {"time": "2026-08-01T00:00:00Z", "equity": "10000"},
                        {"time": "2026-11-01T00:00:00Z", "equity": "11240.55"},
                    ],
                }
            ]
        }
    )


class BacktestRankingRow(BaseModel):
    # 同一标的不同参数组合会各占一行，`run_id` 是回到具体运行的身份。
    run_id: str
    inst_id: str
    inst_type: InstType
    params: dict[str, ParamValue]
    total_return_pct: DecimalString
    max_drawdown_pct: DecimalString
    sharpe: DecimalString
    profit_factor: DecimalString
    trade_count: int


class BacktestRankingResponse(BaseModel):
    data_source: DataSource
    metric: RankingMetric
    items: list[BacktestRankingRow]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "data_source": "okx",
                    "metric": "total_return_pct",
                    "items": [
                        {
                            "run_id": "bt_0001",
                            "inst_id": "XAAPL-USDT",
                            "inst_type": "SPOT",
                            "params": {
                                "reversion_window": 3,
                                "strength_window": 2,
                                "pair_count": 1,
                            },
                            "total_return_pct": "12.4055",
                            "max_drawdown_pct": "-6.12",
                            "sharpe": "1.31",
                            "profit_factor": "1.95",
                            "trade_count": 37,
                        }
                    ],
                }
            ]
        }
    )


class TimeSplit(BaseModel):
    name: Literal["train", "validation", "test"]
    start_date: date
    end_date: date


class BacktestSweepRequest(BaseModel):
    """参数组合扫描：网格 + 训练/验证/样本外切分，防止把最优历史参数当结论。"""

    request: BacktestRequest
    param_grid: dict[str, list[ParamValue]]
    splits: list[TimeSplit]


class BacktestSweepCombo(BaseModel):
    params: dict[str, ParamValue]
    metrics: BacktestMetrics | None = None
    error_message: str | None = None


class BacktestSweepResponse(BaseModel):
    sweep_id: str
    status: RunStatus
    data_source: DataSource
    created_at: UtcDatetime
    combos: list[BacktestSweepCombo]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "sweep_id": "sw_0001",
                    "status": "succeeded",
                    "data_source": "okx",
                    "created_at": "2026-11-10T01:30:00Z",
                    "combos": [
                        {
                            "params": {"fast": 10, "slow": 40},
                            "metrics": None,
                            "error_message": None,
                        }
                    ],
                }
            ]
        }
    )

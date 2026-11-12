"""回测结果的持久化模型：`backtest_runs` / `backtest_trades` / `backtest_equity` 三张表。

三张表对应「一次回测的三层事实」，分开存是因为它们的读取方式不同：

- `backtest_runs`：一次回测的身份与汇总。身份指可复现输入（策略、参数、数据区间、数据源、
  执行模型、数据指纹），汇总指 13 个标的级指标与四项组合级指标。`result_hash` 是这些
  输入的摘要，同参数重跑必然相同。
- `backtest_trades`：逐腿的完整交易（开平仓时刻与价格、成本、盈亏、平仓原因）。给定一次
  回测就能按腿回放，而不是只能看到一串汇总数字。
- `backtest_equity`：逐 bar 的资金曲线，并记下该 bar 在用的净敞口。

时间列沿用 `candles` 的口径：bar 时刻与执行记录时刻存 epoch 秒（整数），与行情表能直接
对齐；数据区间是业务日期，用 `Date`。指标与成本按项目口径存定点数文本（`DecimalText`），
不引入第二套库侧精度。

指标与组合级指标合成 JSON 文本而不是拆成 20 多个列：它们总是整份读出、整份展示，
拆成列只会让表变宽而没有任何查询收益；需要按指标排序时由上层在读出的记录上排序（一次
最多一页）。`params_json` / `costs_json` 同理，都是「原样存、原样读」的可复现输入。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, DecimalText

__all__ = ["BacktestEquityRow", "BacktestRunRow", "BacktestTradeRow"]


class BacktestRunRow(Base):
    """一次回测的运行记录。

    `strategy_instance_id` 不做外键：回测记录是历史事实，实例被删掉之后仍要能按这一行
    回放出当时的结果；策略标识与版本已随行落库，复现依据不依赖实例表还在不在。
    `result_hash` 建索引是因为「同参数重跑」的核对总是按它查。
    """

    __tablename__ = "backtest_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    strategy_instance_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    params_json: Mapped[str] = mapped_column(Text, nullable=False)
    bar: Mapped[str] = mapped_column(String(8), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    data_source: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # 这次回测只跑一个标的：批量回测按标的分成多条运行，排行榜与结果列表才有
    # 可以比较的一行。`inst_type` 与标的表同值，用于区分现货与永续。
    inst_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    inst_type: Mapped[str] = mapped_column(String(8), nullable=False)
    # 发起这次回测的完整请求，原样存、原样读：详情接口要按它重放出同一份输入。
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    data_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_model: Mapped[str] = mapped_column(String(16), nullable=False)
    costs_json: Mapped[str] = mapped_column(Text, nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)
    portfolio_json: Mapped[str] = mapped_column(Text, nullable=False)
    funding_total: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class BacktestTradeRow(Base):
    """一条腿的一次完整交易；`run_id` 删掉时随行删除。

    `trade_id` 由运行标识加序号拼成，同一份结果写两次得到同一批标识，便于比对。
    开平仓时刻存 epoch 秒，与 `backtest_equity.time` 可直接对齐。
    """

    __tablename__ = "backtest_trades"

    trade_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("backtest_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_key: Mapped[str] = mapped_column(String(32), nullable=False)
    inst_id: Mapped[str] = mapped_column(String(32), nullable=False)
    inst_type: Mapped[str] = mapped_column(String(8), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    qty: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    entry_time: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    exit_time: Mapped[int] = mapped_column(Integer, nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    fee: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    slippage: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    pnl: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)


class BacktestEquityRow(Base):
    """资金曲线上的一个点：该 bar 收盘时的净值与该 bar 在用的净敞口。

    主键是（运行标识，bar 时刻）：一次回测在同一时刻只有一个净值点，重复写入即冲突，
    不需要额外去重逻辑。
    """

    __tablename__ = "backtest_equity"

    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("backtest_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    )
    time: Mapped[int] = mapped_column(Integer, primary_key=True)
    equity: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    net_exposure: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)

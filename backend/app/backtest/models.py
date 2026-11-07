"""backtest schema 的 ORM 模型（回测运行、指标、权益点与成交明细）。

列与唯一键严格对应 `docs/architecture/data-model.md` §6。回测只读行情与策略，
不写任何交易域数据；`backtest_trade` 是回测内部的虚拟持仓流水，不是真实成交。
"""

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SCHEMA = "backtest"
MONEY = Numeric(24, 10)
PRICE = Numeric(20, 10)


class BacktestRun(Base):
    """一次回测；`run_key` 唯一，同参数重复提交直接复用已有运行。"""

    __tablename__ = "backtest_run"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("run_key", name="uq_backtest_run_key"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_key: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    strategy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bar: Mapped[str] = mapped_column(Text, nullable=False)
    initial_capital: Mapped[Any] = mapped_column(MONEY, nullable=False)
    cost_model: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class BacktestMetric(Base):
    """一条指标；名称为 10 个固定指标（多窗口时带 `@<窗口名>` 后缀）。"""

    __tablename__ = "backtest_metric"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("run_id", "name", name="uq_backtest_metric_name"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SCHEMA}.backtest_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[Any] = mapped_column(MONEY, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)


class BacktestEquityPoint(Base):
    """权益曲线的一个时点；`drawdown` 为相对历史峰值的负值比例。"""

    __tablename__ = "backtest_equity_point"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("run_id", "ts", name="uq_backtest_equity_point_ts"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SCHEMA}.backtest_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    equity: Mapped[Any] = mapped_column(MONEY, nullable=False)
    cash: Mapped[Any] = mapped_column(MONEY, nullable=False)
    exposure: Mapped[Any] = mapped_column(MONEY, nullable=False)
    drawdown: Mapped[Any] = mapped_column(MONEY, nullable=False)


class BacktestTrade(Base):
    """回测虚拟成交；`exit_reason` 目前只有 `window_end`。"""

    __tablename__ = "backtest_trade"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint(
            "run_id", "instrument_id", "side", "entry_ts", name="uq_backtest_trade_key"
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SCHEMA}.backtest_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instrument.id", ondelete="CASCADE"), nullable=False
    )
    side: Mapped[str] = mapped_column(Text, nullable=False)
    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_px: Mapped[Any] = mapped_column(PRICE, nullable=False)
    exit_px: Mapped[Any] = mapped_column(PRICE, nullable=False)
    qty: Mapped[Any] = mapped_column(MONEY, nullable=False)
    gross_pnl: Mapped[Any] = mapped_column(MONEY, nullable=False)
    fees: Mapped[Any] = mapped_column(MONEY, nullable=False)
    funding: Mapped[Any] = mapped_column(MONEY, nullable=False)
    slippage: Mapped[Any] = mapped_column(MONEY, nullable=False)
    net_pnl: Mapped[Any] = mapped_column(MONEY, nullable=False)
    bars_held: Mapped[int] = mapped_column(Integer, nullable=False)
    exit_reason: Mapped[str] = mapped_column(Text, nullable=False, server_default="window_end")


__all__ = [
    "SCHEMA",
    "BacktestEquityPoint",
    "BacktestMetric",
    "BacktestRun",
    "BacktestTrade",
]

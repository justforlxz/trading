"""S7 历史回测：backtest schema（运行、指标、权益点与成交明细）。

列与唯一键严格对应 `docs/architecture/data-model.md` §6。回测只读市场与策略数据，
不建任何交易域表；`backtest_trade` 是回测内部的虚拟持仓流水。

Revision ID: 0006_backtest_schema
Revises: 0005_strategy_schema
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_backtest_schema"
down_revision: str | None = "0005_strategy_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(24, 10)
PRICE = sa.Numeric(20, 10)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS backtest")

    op.create_table(
        "backtest_run",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("run_key", sa.Text(), nullable=False),
        sa.Column("strategy_id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_version", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bar", sa.Text(), nullable=False),
        sa.Column("initial_capital", MONEY, nullable=False),
        sa.Column(
            "cost_model",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "params",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.UniqueConstraint("run_key", name="uq_backtest_run_key"),
        schema="backtest",
    )

    op.create_table(
        "backtest_metric",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("backtest.backtest_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("value", MONEY, nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.UniqueConstraint("run_id", "name", name="uq_backtest_metric_name"),
        schema="backtest",
    )

    op.create_table(
        "backtest_equity_point",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("backtest.backtest_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("equity", MONEY, nullable=False),
        sa.Column("cash", MONEY, nullable=False),
        sa.Column("exposure", MONEY, nullable=False),
        sa.Column("drawdown", MONEY, nullable=False),
        sa.UniqueConstraint("run_id", "ts", name="uq_backtest_equity_point_ts"),
        schema="backtest",
    )

    op.create_table(
        "backtest_trade",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("backtest.backtest_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "instrument_id",
            sa.BigInteger(),
            sa.ForeignKey("market.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("entry_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_px", PRICE, nullable=False),
        sa.Column("exit_px", PRICE, nullable=False),
        sa.Column("qty", MONEY, nullable=False),
        sa.Column("gross_pnl", MONEY, nullable=False),
        sa.Column("fees", MONEY, nullable=False),
        sa.Column("funding", MONEY, nullable=False),
        sa.Column("slippage", MONEY, nullable=False),
        sa.Column("net_pnl", MONEY, nullable=False),
        sa.Column("bars_held", sa.Integer(), nullable=False),
        sa.Column("exit_reason", sa.Text(), nullable=False, server_default="window_end"),
        sa.UniqueConstraint(
            "run_id", "instrument_id", "side", "entry_ts", name="uq_backtest_trade_key"
        ),
        schema="backtest",
    )


def downgrade() -> None:
    op.drop_table("backtest_trade", schema="backtest")
    op.drop_table("backtest_equity_point", schema="backtest")
    op.drop_table("backtest_metric", schema="backtest")
    op.drop_table("backtest_run", schema="backtest")
    op.execute("DROP SCHEMA IF EXISTS backtest")


__all__ = ["downgrade", "revision", "upgrade"]

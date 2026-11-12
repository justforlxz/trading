"""`backtest_runs` / `backtest_trades` / `backtest_equity`：回测结果的三个层次。

三张表分开是读取方式决定的：运行表存身份与汇总，交易表存逐腿完整交易（给定一次回测
能按腿回放），净值表存逐 bar 的资金曲线与净敞口。指标与组合级指标存 JSON 文本：它们总是
整份读出、整份展示，拆成二十多个列只让表变宽而没有查询收益。

策略实例标识不做外键：回测记录是历史事实，实例删除后仍要能按记录回放；策略标识与版本
已随行落库。交易与净值两表按运行标识级联删除——它们没有脱离运行记录的独立意义。

时间列沿用 `candles` 的口径存 epoch 秒（整数），定点数走文本列。迁移脚本不导入应用代码。

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_instance_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=False),
        sa.Column("bar", sa.String(length=8), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("data_source", sa.String(length=16), nullable=False),
        sa.Column("data_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("execution_model", sa.String(length=16), nullable=False),
        sa.Column("costs_json", sa.Text(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("portfolio_json", sa.Text(), nullable=False),
        sa.Column("funding_total", sa.String(length=128), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        "ix_backtest_runs_strategy_instance_id",
        "backtest_runs",
        ["strategy_instance_id"],
        unique=False,
    )
    op.create_index(
        "ix_backtest_runs_data_source",
        "backtest_runs",
        ["data_source"],
        unique=False,
    )
    op.create_index(
        "ix_backtest_runs_result_hash",
        "backtest_runs",
        ["result_hash"],
        unique=False,
    )
    op.create_table(
        "backtest_trades",
        sa.Column("trade_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("product_key", sa.String(length=32), nullable=False),
        sa.Column("inst_id", sa.String(length=32), nullable=False),
        sa.Column("inst_type", sa.String(length=8), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("qty", sa.String(length=128), nullable=False),
        sa.Column("entry_time", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.String(length=128), nullable=False),
        sa.Column("exit_time", sa.Integer(), nullable=False),
        sa.Column("exit_price", sa.String(length=128), nullable=False),
        sa.Column("fee", sa.String(length=128), nullable=False),
        sa.Column("slippage", sa.String(length=128), nullable=False),
        sa.Column("pnl", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["backtest_runs.run_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("trade_id"),
    )
    op.create_index(
        "ix_backtest_trades_run_id",
        "backtest_trades",
        ["run_id"],
        unique=False,
    )
    op.create_table(
        "backtest_equity",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("time", sa.Integer(), nullable=False),
        sa.Column("equity", sa.String(length=128), nullable=False),
        sa.Column("net_exposure", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["backtest_runs.run_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", "time"),
    )


def downgrade() -> None:
    op.drop_table("backtest_equity")
    op.drop_index("ix_backtest_trades_run_id", table_name="backtest_trades")
    op.drop_table("backtest_trades")
    op.drop_index("ix_backtest_runs_result_hash", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_data_source", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_strategy_instance_id", table_name="backtest_runs")
    op.drop_table("backtest_runs")

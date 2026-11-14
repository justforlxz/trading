"""v6 用户策略：策略、不可变版本、版本标的与回测关联。

四张表：

- `strategies`：用户策略的身份与展示属性；
- `strategy_versions`：规则、参数、周期、方向、仓位规则与成本假设，`(strategy_id, version)` 唯一；
- `strategy_instruments`：策略版本关联的标的集合；
- `strategy_linked_backtests`：回测运行与策略版本的正式关联；

版本一经创建不可修改：改规则必须新建下一版，历史回测通过
`strategy_linked_backtests` 指向具体版本。时间列沿用 `UtcDateTime` 的无时区 UTC
口径；JSON 列存文本，由域层校验与序列化。迁移脚本不导入应用代码。

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategies",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_strategies_status", "strategies", ["status"], unique=False)
    op.create_index("ix_strategies_category", "strategies", ["category"], unique=False)

    op.create_table(
        "strategy_versions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("rule_json", sa.Text(), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("position_sizing_json", sa.Text(), nullable=True),
        sa.Column("cost_model_json", sa.Text(), nullable=True),
        sa.Column("change_note", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("strategy_id", "version", name="uq_strategy_versions"),
    )
    op.create_index(
        "ix_strategy_versions_strategy_id", "strategy_versions", ["strategy_id"], unique=False
    )

    op.create_table(
        "strategy_instruments",
        sa.Column("strategy_version_id", sa.String(length=64), nullable=False),
        sa.Column("instrument_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"], ["strategy_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.symbol"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("strategy_version_id", "instrument_id"),
    )
    op.create_index(
        "ix_strategy_instruments_instrument_id",
        "strategy_instruments",
        ["instrument_id"],
        unique=False,
    )

    op.create_table(
        "strategy_linked_backtests",
        sa.Column("strategy_version_id", sa.String(length=64), nullable=False),
        sa.Column("backtest_run_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"], ["strategy_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["backtest_run_id"], ["backtest_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("strategy_version_id", "backtest_run_id"),
    )
    op.create_index(
        "ix_strategy_linked_backtests_strategy_version_id",
        "strategy_linked_backtests",
        ["strategy_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_strategy_linked_backtests_backtest_run_id",
        "strategy_linked_backtests",
        ["backtest_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_strategy_linked_backtests_backtest_run_id",
        table_name="strategy_linked_backtests",
    )
    op.drop_index(
        "ix_strategy_linked_backtests_strategy_version_id",
        table_name="strategy_linked_backtests",
    )
    op.drop_table("strategy_linked_backtests")
    op.drop_index("ix_strategy_instruments_instrument_id", table_name="strategy_instruments")
    op.drop_table("strategy_instruments")
    op.drop_index("ix_strategy_versions_strategy_id", table_name="strategy_versions")
    op.drop_table("strategy_versions")
    op.drop_index("ix_strategies_category", table_name="strategies")
    op.drop_index("ix_strategies_status", table_name="strategies")
    op.drop_table("strategies")

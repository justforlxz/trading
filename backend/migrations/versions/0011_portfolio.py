"""全局组合管理：策略级虚拟持仓、虚拟成交、资金分配与调整申请。

四张新表，全部挂在 `strategy_instances` 上（`ON DELETE CASCADE`）：策略实例不存在时，
它的账本、分配与申请都没有独立意义。

- `virtual_positions`：一个（实例，标的）的账本投影。主键是复合键；`direction` 与
  `opened_at` 可空，因为「已平仓」是一个真实状态。
- `virtual_fills`：成交流水，账本的事实来源；`fill_id` 是主键。
- `allocations`：一个实例的预算、优先级与已批准生效的目标组合（JSON 文本）。
- `portfolio_adjustments`：申请与决定。申请说明与决定说明分两列存，接口只暴露一个
  `note`（优先取决定说明）。

迁移脚本不导入应用代码。

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "virtual_positions",
        sa.Column("instance_id", sa.String(length=64), nullable=False),
        sa.Column("inst_id", sa.String(length=64), nullable=False),
        sa.Column("inst_type", sa.String(length=16), nullable=False),
        sa.Column("product_key", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=True),
        sa.Column("qty", sa.String(length=64), nullable=False),
        sa.Column("avg_cost", sa.String(length=64), nullable=False),
        sa.Column("mark_price", sa.String(length=64), nullable=True),
        sa.Column("realized_pnl", sa.String(length=64), nullable=False),
        sa.Column("fees", sa.String(length=64), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["strategy_instances.instance_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("instance_id", "inst_id"),
    )
    op.create_index(
        "ix_virtual_positions_product_key",
        "virtual_positions",
        ["product_key"],
        unique=False,
    )
    op.create_table(
        "virtual_fills",
        sa.Column("fill_id", sa.String(length=64), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("instance_id", sa.String(length=64), nullable=False),
        sa.Column("inst_id", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("qty", sa.String(length=64), nullable=False),
        sa.Column("price", sa.String(length=64), nullable=False),
        sa.Column("fee", sa.String(length=64), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["strategy_instances.instance_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("fill_id"),
    )
    op.create_index(
        "ix_virtual_fills_instance_id",
        "virtual_fills",
        ["instance_id"],
        unique=False,
    )
    op.create_table(
        "allocations",
        sa.Column("instance_id", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("capital_budget", sa.String(length=64), nullable=False),
        sa.Column("target_json", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["strategy_instances.instance_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("instance_id"),
    )
    op.create_table(
        "portfolio_adjustments",
        sa.Column("adjustment_id", sa.String(length=64), nullable=False),
        sa.Column("instance_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_by", sa.String(length=128), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("decided_by", sa.String(length=128), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("decision_note", sa.String(length=512), nullable=True),
        sa.Column("target_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["strategy_instances.instance_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("adjustment_id"),
    )
    op.create_index(
        "ix_portfolio_adjustments_instance_id",
        "portfolio_adjustments",
        ["instance_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_adjustments_instance_id", table_name="portfolio_adjustments")
    op.drop_table("portfolio_adjustments")
    op.drop_table("allocations")
    op.drop_index("ix_virtual_fills_instance_id", table_name="virtual_fills")
    op.drop_table("virtual_fills")
    op.drop_index("ix_virtual_positions_product_key", table_name="virtual_positions")
    op.drop_table("virtual_positions")

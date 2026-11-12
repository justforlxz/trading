"""策略生命周期的审批状态机：实例上的推进事实与审批记录表。

两处结构变更：

1. `strategy_instances.status` 改名为 `lifecycle_status`。这一列从 T3.3 起就承载生命周期
   阶段（当时的取值只有草稿），本节点把它交给审批状态机推进，并换成不含歧义的名字；
   对外契约字段仍是 `status`，由接口层映射，不产生第二列来重复同一个事实。
2. 新增 `approved_by` / `approved_at` / `validation_report_id` / `live_authorized_at`
   四列：它们记录审核通过、量化验证达标、实盘授权这三件已经发生的事，未发生的推进留空。

另建 `strategy_approvals`：每一次阶段推进写一条记录，含推进人、起始阶段、目标阶段与
时刻。记录是历史事实，只增不改；`instance_id` 带 `ON DELETE CASCADE`，实例删掉之后
记录没有独立意义。表上另有一个数据库序列发放的 `seq`：`at` 只有秒精度，同一秒内的多条
推进靠它才有确定的先后顺序，审批记录列表按这个顺序展示。

迁移脚本不导入应用代码：历史脚本描述的是一段已发生的结构变更，不能随实现变化。

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "strategy_instances",
        "status",
        new_column_name="lifecycle_status",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
    op.add_column(
        "strategy_instances",
        sa.Column("approved_by", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "strategy_instances",
        sa.Column("approved_at", sa.Integer(), nullable=True),
    )
    op.add_column(
        "strategy_instances",
        sa.Column("validation_report_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "strategy_instances",
        sa.Column("live_authorized_at", sa.Integer(), nullable=True),
    )
    op.create_table(
        "strategy_approvals",
        sa.Column("approval_id", sa.String(length=64), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("instance_id", sa.String(length=64), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("at", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("evidence", sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["strategy_instances.instance_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("approval_id"),
    )
    op.create_index(
        "ix_strategy_approvals_instance_id",
        "strategy_approvals",
        ["instance_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_approvals_instance_id", table_name="strategy_approvals")
    op.drop_table("strategy_approvals")
    op.drop_column("strategy_instances", "live_authorized_at")
    op.drop_column("strategy_instances", "validation_report_id")
    op.drop_column("strategy_instances", "approved_at")
    op.drop_column("strategy_instances", "approved_by")
    op.alter_column(
        "strategy_instances",
        "lifecycle_status",
        new_column_name="status",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )

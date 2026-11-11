"""`strategy_replays`：目标组合回放的执行记录。

回放按历史行情把模板重算一遍，把「这一区间上目标组合是什么」连同逐点净敞口一起
落库。行是执行记录而不是配置：同一实例同一区间回放两次会有两行，但 `target_hash`
必须相同，可复现的判据落在这一列上。

`result_json` / `points_json` 沿用实例表 params / inst_ids 的口径，存 JSON 文本；
`instance_id` 带 `ON DELETE CASCADE`：实例删掉之后，它的回放记录没有独立意义。

迁移脚本不导入应用代码：历史脚本描述的是一段已发生的结构变更，不能随实现变化。

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategy_replays",
        sa.Column("replay_id", sa.String(length=64), nullable=False),
        sa.Column("instance_id", sa.String(length=64), nullable=False),
        sa.Column("bar", sa.String(length=8), nullable=False),
        sa.Column("start_at", sa.Integer(), nullable=False),
        sa.Column("end_at", sa.Integer(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("target_hash", sa.String(length=64), nullable=False),
        sa.Column("points_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["strategy_instances.instance_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("replay_id"),
    )
    op.create_index(
        "ix_strategy_replays_instance_id",
        "strategy_replays",
        ["instance_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_replays_instance_id", table_name="strategy_replays")
    op.drop_table("strategy_replays")

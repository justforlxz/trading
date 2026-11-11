"""`strategy_templates` / `strategy_instances`：模板只读投影与用户实例分开两张表。

模板行的内容是代码注册表的投影（`app/strategy/registry.py` 的 import-time 登记），
表里没有任何写入口；实例行是用户配置，`strategy_id` 外键指回模板，因此「这个实例
用的是哪套组合方式」始终有答案，也不会出现指向不存在模板的孤儿实例。

两表各带一份版本：`strategy_templates.version` 是模板当前版本，
`strategy_instances.strategy_version` 是实例创建时的模板版本。后者不随模板升级回填——
历史实例要报自己那一版，回放与复现才有依据。

时间列沿用 `candles` 的口径存 epoch 秒（整数）；参数与标的是 JSON 文本。列宽与模型
一致（`VARCHAR(64/128/512/1024/8/32/16)`），`enabled` 是布尔、默认真。

迁移脚本不导入应用代码：历史脚本描述的是一段已发生的结构变更，不能随实现变化。

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategy_templates",
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.String(length=512), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("strategy_id"),
    )
    op.create_table(
        "strategy_instances",
        sa.Column("instance_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("bar", sa.String(length=8), nullable=False),
        sa.Column("params", sa.String(length=1024), nullable=False, server_default="{}"),
        sa.Column("inst_ids", sa.String(length=1024), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("latest_signal_at", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategy_templates.strategy_id"]),
        sa.PrimaryKeyConstraint("instance_id"),
    )
    op.create_index(
        "ix_strategy_instances_strategy_id",
        "strategy_instances",
        ["strategy_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_instances_strategy_id", table_name="strategy_instances")
    op.drop_table("strategy_instances")
    op.drop_table("strategy_templates")

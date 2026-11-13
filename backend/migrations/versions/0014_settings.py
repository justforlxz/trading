"""设置文档：单行保存可编辑配置与只写不读的 API Key。

表结构与 `app/settings/model.py` 一致：分组以 JSON 文本保存，时间列沿用
`UtcDateTime` 的无时区 UTC 口径。迁移脚本不导入应用代码。

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("execution", sa.Text(), nullable=False),
        sa.Column("risk", sa.Text(), nullable=False),
        sa.Column("costs", sa.Text(), nullable=False),
        sa.Column("backtest", sa.Text(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("okx_api_key", sa.String(length=512), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("settings")

"""分级风险处置：在 T6.1 的 `risk_events` 上追加四列。

`risk_events` 表由 0012 创建，本迁移只追加列，不新建表。四列含义：

- `severity`：`light` / `medium` / `severe`。
- `action`：本次处置动作，多个动作用逗号连接。
- `target_product_key`：处置针对的产品键。
- `overridden_approval_id`：被本次处置覆盖的待批准组合申请。

迁移脚本不导入应用代码。

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("risk_events", sa.Column("severity", sa.String(length=16), nullable=True))
    op.add_column("risk_events", sa.Column("action", sa.String(length=64), nullable=True))
    op.add_column(
        "risk_events",
        sa.Column("target_product_key", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "risk_events",
        sa.Column("overridden_approval_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("risk_events", "overridden_approval_id")
    op.drop_column("risk_events", "target_product_key")
    op.drop_column("risk_events", "action")
    op.drop_column("risk_events", "severity")

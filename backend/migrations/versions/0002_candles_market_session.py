"""`candles` 增加 `market_session`：记录每根 K 线所属的资产时段。

存量行没有时段语义可推断（同一个标的在不同时段都可能落过日线），因此按「未知」
回填空串，而不是猜一个值。列类型与模型一致：`VARCHAR(16)`、非空、默认空串。

迁移脚本不导入应用代码：历史脚本描述的是一段已发生的结构变更，不能随实现变化。

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candles",
        sa.Column("market_session", sa.String(length=16), nullable=False, server_default=""),
    )
    op.alter_column("candles", "market_session", server_default=None)


def downgrade() -> None:
    op.drop_column("candles", "market_session")

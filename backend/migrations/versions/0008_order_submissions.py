"""`order_submissions`：下单意图的幂等键登记表。

一行等于一个 `clientOrderId`。这张表的存在理由只有一个：**在下单请求发出去之前**
先把键登记下来，重启之后才知道「这张单可能已经发出去了」，于是先去上游查，而不是
盲目重发。

`status` 记录的是本地知道的事实（`recorded` / `submitted` / `rejected`），不是订单
状态机的状态；上游订单状态（`live` / `filled` / `canceled`）由执行层维护，不在这张表里。

价格与数量沿用全仓口径，用文本列存 `Decimal`；时间列折算成 UTC 存无时区值。

迁移脚本不导入应用代码：历史脚本描述的是一段已发生的结构变更，不能随实现变化。

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "order_submissions",
        sa.Column("client_order_id", sa.String(length=64), nullable=False),
        sa.Column("inst_id", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("qty", sa.String(), nullable=False),
        sa.Column("price", sa.String(), nullable=True),
        sa.Column("order_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("client_order_id"),
    )


def downgrade() -> None:
    op.drop_table("order_submissions")

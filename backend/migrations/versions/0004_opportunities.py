"""`opportunities`：机会发现的候选记录。

主键是 `opportunity_id`——由「模式 + 锚点 + `as_of` + 腿」派生，同一份输入重复检测
得到同一个标识，重复执行只会命中已有行，不会追加副本。

两个 JSON 文本列分工不同：`evidence` 是判定依据，`legs` 是候选腿本身。腿必须随机会
一起落库：回看一条机会时重算等于换了行情，那不是同一条机会。

`status` 的取值与流转规则属于服务层，这里不建枚举——迁移脚本不描述业务规则。

迁移脚本不导入应用代码：历史脚本描述的是一段已发生的结构变更，不能随实现变化。

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "opportunities",
        sa.Column("opportunity_id", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("anchor_product_key", sa.String(length=32), nullable=True),
        sa.Column("as_of", sa.DateTime(), nullable=False),
        sa.Column("score", sa.String(), nullable=False),
        sa.Column("legs", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("opportunity_id"),
    )
    # 列表按模式、锚点与状态各自过滤，三个条件都可能单独出现。
    op.create_index("ix_opportunities_mode", "opportunities", ["mode"], unique=False)
    op.create_index(
        "ix_opportunities_anchor_product_key",
        "opportunities",
        ["anchor_product_key"],
        unique=False,
    )
    op.create_index("ix_opportunities_status", "opportunities", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_opportunities_status", table_name="opportunities")
    op.drop_index("ix_opportunities_anchor_product_key", table_name="opportunities")
    op.drop_index("ix_opportunities_mode", table_name="opportunities")
    op.drop_table("opportunities")

"""`exchange_position_snapshots.stop_status` 允许为空，并去掉列默认值。

0024 给这一列设了 `'unavailable'` 默认值，于是「这一行没写止损信息」（私有频道推送
写行时按设计不带止损列）与「问过、没问成」落成了同一个值。读侧按「最近一条带结论的
行」取止损时，两者混起来就没有办法把推送行排除在外，卡片上 15 条持仓会一直显示
「未取到」。

升级后 NULL 表示这一行没带止损信息，`confirmed` / `none` / `unavailable` 才是写进去
的结论。历史行里的 `'unavailable'` 不搬动：它们确实从没问过止损，读侧只认
`confirmed` / `none`，这些行本来就会被跳过，没必要为了改标签扫描几万行。

迁移脚本不导入应用代码。

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "exchange_position_snapshots",
        "stop_status",
        existing_type=sa.String(length=16),
        nullable=True,
        server_default=None,
    )


def downgrade() -> None:
    # 回到 NOT NULL 之前先把空值补成 `unavailable`：那是升级前这些行的取值。
    op.execute(
        "UPDATE exchange_position_snapshots SET stop_status = 'unavailable' "
        "WHERE stop_status IS NULL"
    )
    op.alter_column(
        "exchange_position_snapshots",
        "stop_status",
        existing_type=sa.String(length=16),
        nullable=False,
        server_default="unavailable",
    )

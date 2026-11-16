"""账户快照记录本次是否携带持仓批次。

新增 `account_snapshots.positions_included`：账户推送不保证同时带来持仓明细，缺少
批次时无法判断当时是否有持仓。该标记区分「明确记录的空持仓」与「这次没有携带
持仓」，让汇总接口在后者返回未知，而不是报成 0。

存量数据回填：同一账户、同一采集时刻存在持仓行时标记为 `true`；没有持仓行的历史
账户快照保持 `false`，读取时按未知处理。

迁移脚本不导入应用代码。

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "account_snapshots",
        sa.Column(
            "positions_included",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        """
        UPDATE account_snapshots AS account
        SET positions_included = true
        WHERE EXISTS (
            SELECT 1
            FROM exchange_position_snapshots AS position
            WHERE position.account_id = account.account_id
              AND position.captured_at = account.captured_at
        )
        """
    )


def downgrade() -> None:
    op.drop_column("account_snapshots", "positions_included")

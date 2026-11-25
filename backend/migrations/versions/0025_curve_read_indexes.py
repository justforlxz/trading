"""两张快照表补 `captured_at` 索引：权益曲线与持仓盈亏曲线按时间范围读。

两个查询都只按 `captured_at >= 起点` 过滤，不带 `account_id`：

- `app.positions.curves.equity_curve` 读 `account_snapshots`；
- `app.positions.curves.upl_curves` 读 `exchange_position_snapshots`。

现有索引都以 `account_id` 打头（`account_snapshots` 的唯一约束
`(account_id, captured_at, source)`、`exchange_position_snapshots` 的
`(account_id, captured_at)`），等值前缀缺第一列时用不上，只能退化成顺序扫。
新增两条只含 `captured_at` 的索引，让范围扫描走索引。

迁移脚本不导入应用代码。

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_account_snapshots_captured",
        "account_snapshots",
        ["captured_at"],
    )
    op.create_index(
        "ix_exchange_position_snapshots_captured",
        "exchange_position_snapshots",
        ["captured_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_exchange_position_snapshots_captured", table_name="exchange_position_snapshots"
    )
    op.drop_index("ix_account_snapshots_captured", table_name="account_snapshots")

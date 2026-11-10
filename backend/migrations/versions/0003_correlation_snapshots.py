"""`correlation_snapshots`：一组标的在某个时刻、某个窗口上的相关矩阵快照。

主键 `(product_key_a, product_key_b, bar, window, as_of)` 就是「同一条关系在同一时点
只能有一份数值」的约束，重复保存走覆盖而不是追加。标识用产品键（`VARCHAR(32)`，与
`instruments.product_key` 同长度），不是交易所标识；对角线也入库，`samples` 才带着
「这个标的有多少条样本」这一事实。

`coefficient` 用双精度浮点：无量纲系数不需要十进制文本往返，空值表示「无法计算」，
与「系数恰好为 0」是两件不同的事。`as_of` 沿用 `candles` 的口径存 epoch 秒。

迁移脚本不导入应用代码：历史脚本描述的是一段已发生的结构变更，不能随实现变化。

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "correlation_snapshots",
        sa.Column("product_key_a", sa.String(length=32), nullable=False),
        sa.Column("product_key_b", sa.String(length=32), nullable=False),
        sa.Column("bar", sa.String(length=8), nullable=False),
        sa.Column("window", sa.Integer(), nullable=False),
        sa.Column("as_of", sa.Integer(), nullable=False),
        sa.Column("coefficient", sa.Float(), nullable=True),
        sa.Column("samples", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("product_key_a", "product_key_b", "bar", "window", "as_of"),
    )
    # 回看按 (bar, window, as_of) 过滤，主键首列是产品键，用不上这条过滤条件。
    op.create_index(
        "ix_correlation_snapshots_bar_window_as_of",
        "correlation_snapshots",
        ["bar", "window", "as_of"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_correlation_snapshots_bar_window_as_of", table_name="correlation_snapshots")
    op.drop_table("correlation_snapshots")

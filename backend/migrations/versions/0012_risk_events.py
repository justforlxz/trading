"""`risk_events`：每次风控拒绝的审计记录。

本表只保存「哪条规则拒绝了哪个实例与标的、原因是什么、何时发生」。分级处置要用的
严重程度、动作、处置目标与被覆盖的申请，由 T6.5 在同一张表上追加，本迁移不预建。

迁移脚本不导入应用代码。

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "risk_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("instance_id", sa.String(length=64), nullable=True),
        sa.Column("inst_id", sa.String(length=64), nullable=True),
        sa.Column("rule", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_risk_events_instance_id", "risk_events", ["instance_id"])
    op.create_index("ix_risk_events_inst_id", "risk_events", ["inst_id"])
    op.create_index("ix_risk_events_rule", "risk_events", ["rule"])
    op.create_index("ix_risk_events_created_at", "risk_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_risk_events_created_at", table_name="risk_events")
    op.drop_index("ix_risk_events_rule", table_name="risk_events")
    op.drop_index("ix_risk_events_inst_id", table_name="risk_events")
    op.drop_index("ix_risk_events_instance_id", table_name="risk_events")
    op.drop_table("risk_events")

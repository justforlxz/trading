"""v6 记录、提醒与活动：研究记录、提醒事件、活动事件，并删除旧价格提醒。

`price_alerts` 是 v2 挂在自选条目上的价格提醒，v6 没有价格提醒入口；由
`alert_events` 取代。旧提醒数据不迁移：迁移过去也没有入口再触发或展示。
时间列沿用 `UtcDateTime` 的无时区 UTC 口径；JSON 列存文本，由域层校验与序列化。
迁移脚本不导入应用代码。

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_notes",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("instrument_id", sa.String(length=64), nullable=True),
        sa.Column("strategy_id", sa.String(length=64), nullable=True),
        sa.Column("backtest_id", sa.String(length=64), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.symbol"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["backtest_id"], ["backtest_runs.run_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_research_notes_type_created", "research_notes", ["type", "created_at"], unique=False
    )
    op.create_index(
        "ix_research_notes_instrument", "research_notes", ["instrument_id"], unique=False
    )
    op.create_index("ix_research_notes_strategy", "research_notes", ["strategy_id"], unique=False)
    op.create_index("ix_research_notes_backtest", "research_notes", ["backtest_id"], unique=False)

    op.create_table(
        "alert_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("instrument_id", sa.String(length=64), nullable=True),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("rule_version", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("dedup_key", sa.String(length=256), nullable=False),
        sa.Column("triggered_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.symbol"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_key", name="uq_alert_events_dedup_key"),
    )
    op.create_index(
        "ix_alert_events_status_triggered",
        "alert_events",
        ["status", "triggered_at"],
        unique=False,
    )
    op.create_index(
        "ix_alert_events_type_instrument",
        "alert_events",
        ["type", "instrument_id"],
        unique=False,
    )

    op.create_table(
        "activity_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=False),
        sa.Column("object_id", sa.String(length=128), nullable=False),
        sa.Column("summary", sa.String(length=512), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_activity_events_created_at_id",
        "activity_events",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_activity_events_event_type", "activity_events", ["event_type"], unique=False
    )
    op.create_index(
        "ix_activity_events_object", "activity_events", ["object_type", "object_id"], unique=False
    )

    op.drop_table("price_alerts")


def downgrade() -> None:
    op.create_table(
        "price_alerts",
        sa.Column("inst_id", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("price", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["inst_id"], ["watchlist_items.inst_id"]),
        sa.PrimaryKeyConstraint("inst_id"),
    )

    op.drop_index("ix_activity_events_object", table_name="activity_events")
    op.drop_index("ix_activity_events_event_type", table_name="activity_events")
    op.drop_index("ix_activity_events_created_at_id", table_name="activity_events")
    op.drop_table("activity_events")

    op.drop_index("ix_alert_events_type_instrument", table_name="alert_events")
    op.drop_index("ix_alert_events_status_triggered", table_name="alert_events")
    op.drop_table("alert_events")

    op.drop_index("ix_research_notes_backtest", table_name="research_notes")
    op.drop_index("ix_research_notes_strategy", table_name="research_notes")
    op.drop_index("ix_research_notes_instrument", table_name="research_notes")
    op.drop_index("ix_research_notes_type_created", table_name="research_notes")
    op.drop_table("research_notes")

"""通知通道配置与投递台账。

通知通道的开关放在设置文档里（`settings.notifications`），不写在仓库的代码或环境变量
里：换一台机器、换一个人用，开关跟着数据库走。本期只有 `browser` 一种实现，配置里出现
不认识的名字时由通道注册表忽略，不假装支持。

`notification_deliveries` 是投递台账，一行一次投递：哪条告警、走哪个通道、成没成、
什么时候、失败原因。

迁移脚本不导入应用代码。

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_NOTIFICATIONS = '{"channels":["browser"]}'


def upgrade() -> None:
    # 已有设置行必须先有一个合法值：先带默认值加列，再撤掉默认值，交给域层负责。
    op.add_column(
        "settings",
        sa.Column(
            "notifications",
            sa.Text(),
            nullable=False,
            server_default=DEFAULT_NOTIFICATIONS,
        ),
    )
    op.alter_column("settings", "notifications", server_default=None)

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("alert_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notification_deliveries_alert",
        "notification_deliveries",
        ["alert_id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_deliveries_created",
        "notification_deliveries",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notification_deliveries_created", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_alert", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
    op.drop_column("settings", "notifications")

"""v6 外部市场、新闻同步与设置扩展。

新增三张表：

- `market_events`：宏观与公司事件，时间统一保存 UTC，展示时再由接口转北京时间；
- `news_items`：已采集新闻，保留来源、URL、发布时间与 ticker 标签；
- `data_sync_jobs`：外部数据同步任务与最后成功时间，健康接口只读它，不临时探测。

`settings` 增加显示偏好、风险默认值、数据源三组 JSON 文本，并删除 v6 不再展示的
代理分组。成本与回测默认值仍保留在原列里，只在服务端内部使用，不再经 HTTP 返回。
迁移脚本不导入应用代码。

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("region", sa.String(length=32), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("actual", sa.Text(), nullable=True),
        sa.Column("forecast", sa.Text(), nullable=True),
        sa.Column("previous", sa.Text(), nullable=True),
        sa.Column("importance", sa.String(length=16), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_market_events_scheduled", "market_events", ["scheduled_at"], unique=False)
    op.create_index(
        "ix_market_events_ticker_scheduled",
        "market_events",
        ["ticker", "scheduled_at"],
        unique=False,
    )

    op.create_table(
        "news_items",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("publisher", sa.String(length=128), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("tickers_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "provider_id", name="uq_news_items_source_provider"),
    )
    op.create_index("ix_news_items_published", "news_items", ["published_at"], unique=False)
    op.create_index("ix_news_items_source_published", "news_items", ["source", "published_at"])

    op.create_table(
        "data_sync_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("dataset", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_data_sync_jobs_dataset_started",
        "data_sync_jobs",
        ["dataset", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_data_sync_jobs_provider_started",
        "data_sync_jobs",
        ["provider", "started_at"],
        unique=False,
    )

    op.add_column(
        "settings",
        sa.Column("display", sa.Text(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "settings",
        sa.Column("risk_defaults", sa.Text(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "settings",
        sa.Column("data_sources", sa.Text(), nullable=False, server_default="{}"),
    )
    op.drop_column("settings", "data")


def downgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("data", sa.Text(), nullable=False, server_default="{}"),
    )
    op.drop_column("settings", "data_sources")
    op.drop_column("settings", "risk_defaults")
    op.drop_column("settings", "display")

    op.drop_index("ix_data_sync_jobs_provider_started", table_name="data_sync_jobs")
    op.drop_index("ix_data_sync_jobs_dataset_started", table_name="data_sync_jobs")
    op.drop_table("data_sync_jobs")

    op.drop_index("ix_news_items_source_published", table_name="news_items")
    op.drop_index("ix_news_items_published", table_name="news_items")
    op.drop_table("news_items")

    op.drop_index("ix_market_events_ticker_scheduled", table_name="market_events")
    op.drop_index("ix_market_events_scheduled", table_name="market_events")
    op.drop_table("market_events")

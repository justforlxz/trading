"""删除外部市场 Provider、新闻/事件与美股代理行情。

这些功能没有配置入口，也没有真实数据来源：外部指数依赖未登记的 Provider，
新闻/事件依赖无人采集的表，美股代理行情依赖 Yahoo 免费接口（实测 429）。本次迁移
删除两张表与相关的同步任务、代理 K 线和代理回测记录，并清掉设置文档里残留的
`provider` 键。

迁移脚本不导入应用代码。

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM data_sync_jobs WHERE dataset IN ('market_overview', 'market_events', 'news')"
    )
    op.execute("DELETE FROM candles WHERE source = 'us_equity_proxy'")
    op.execute("DELETE FROM backtest_runs WHERE data_source = 'us_equity_proxy'")
    op.execute("UPDATE settings SET data_sources = (data_sources::jsonb - 'provider')::text")

    op.drop_index("ix_news_items_source_published", table_name="news_items")
    op.drop_index("ix_news_items_published", table_name="news_items")
    op.drop_table("news_items")

    op.drop_index("ix_market_events_ticker_scheduled", table_name="market_events")
    op.drop_index("ix_market_events_scheduled", table_name="market_events")
    op.drop_table("market_events")


def downgrade() -> None:
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

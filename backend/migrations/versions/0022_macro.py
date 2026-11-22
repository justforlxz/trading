"""宏观数据表：观测值。

`macro_observations` 存观测值，主键 `(series_id, ts, provider)` 让重复抓取变成幂等
upsert。`ts` 是 UTC epoch 秒。序列的名称与单位来自代码里的序列清单，来源地址由当前
provider 配置决定，不另存定义表。

`trading_day` 与 `market_session` 是派生列：由 `enrich` 中间件按 `ts` 算出后落库，
供利差按结算日配对、以及界面显示时段；`is_delayed` 记录这条值是不是延迟行情。

迁移脚本不导入应用代码。

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "macro_observations",
        sa.Column("series_id", sa.String(length=32), nullable=False),
        sa.Column("ts", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("value", sa.String(length=32), nullable=False),
        sa.Column("trading_day", sa.Date(), nullable=False),
        sa.Column("market_session", sa.String(length=16), nullable=False),
        sa.Column("is_delayed", sa.Boolean(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("series_id", "ts", "provider"),
    )
    op.create_index(
        "ix_macro_observations_series_provider_day",
        "macro_observations",
        ["series_id", "provider", "trading_day"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_macro_observations_series_provider_day", table_name="macro_observations")
    op.drop_table("macro_observations")

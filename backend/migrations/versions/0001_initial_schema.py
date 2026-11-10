"""初始表结构：把当前 `Base.metadata` 的六张业务表一次性落成 PostgreSQL DDL。

类型口径必须与模型一致，否则 autogenerate 会一直报差异：

- `DecimalText` 的底层是文本列，落成 `VARCHAR`（金额、价格全部以十进制字符串
  往返，精度约定只有一套，不换 `NUMERIC`）。`candles` 的 OHLCV 与 `funding` 的两档
  费率限长 32，其余列不限长。
- `UtcDateTime` 的底层是 `DateTime`，落成 `TIMESTAMP WITHOUT TIME ZONE`：库里存
  折算成 UTC 的无时区值，读出时补回 UTC 时区。

迁移脚本不导入应用代码：历史脚本描述的是一段已发生的结构变更，不能随实现变化。

Revision ID: 0001
Revises:
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candles",
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("bar", sa.String(length=8), nullable=False),
        sa.Column("open_time", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("open", sa.String(length=32), nullable=False),
        sa.Column("high", sa.String(length=32), nullable=False),
        sa.Column("low", sa.String(length=32), nullable=False),
        sa.Column("close", sa.String(length=32), nullable=False),
        sa.Column("volume", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "bar", "open_time", "source"),
    )
    op.create_table(
        "funding",
        sa.Column("inst_id", sa.String(length=64), nullable=False),
        sa.Column("funding_time", sa.Integer(), nullable=False),
        sa.Column("funding_rate", sa.String(length=32), nullable=True),
        sa.Column("realized_rate", sa.String(length=32), nullable=True),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("inst_id", "funding_time"),
    )
    op.create_table(
        "instruments",
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("inst_type", sa.String(length=16), nullable=False),
        sa.Column("product_key", sa.String(length=32), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("base_currency", sa.String(length=32), nullable=False),
        sa.Column("quote_currency", sa.String(length=16), nullable=False),
        sa.Column("tick_size", sa.String(), nullable=True),
        sa.Column("lot_size", sa.String(), nullable=True),
        sa.Column("min_order_size", sa.String(), nullable=True),
        sa.Column("listing_time", sa.DateTime(), nullable=True),
        sa.Column("trading_status", sa.String(length=16), nullable=False),
        sa.Column("data_start", sa.DateTime(), nullable=True),
        sa.Column("ct_val", sa.String(), nullable=True),
        sa.Column("ct_mult", sa.String(), nullable=True),
        sa.Column("ct_type", sa.String(length=16), nullable=True),
        sa.Column("max_lever", sa.String(), nullable=True),
        sa.Column("settle_ccy", sa.String(length=16), nullable=True),
        sa.PrimaryKeyConstraint("symbol"),
    )
    op.create_index(op.f("ix_instruments_inst_type"), "instruments", ["inst_type"], unique=False)
    op.create_index(
        op.f("ix_instruments_product_key"), "instruments", ["product_key"], unique=False
    )
    op.create_table(
        "watchlists",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_table(
        "watchlist_items",
        sa.Column("inst_id", sa.String(length=64), nullable=False),
        sa.Column("group_name", sa.String(length=64), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["group_name"], ["watchlists.name"]),
        sa.ForeignKeyConstraint(["inst_id"], ["instruments.symbol"]),
        sa.PrimaryKeyConstraint("inst_id"),
    )
    op.create_index(
        op.f("ix_watchlist_items_group_name"), "watchlist_items", ["group_name"], unique=False
    )
    op.create_table(
        "price_alerts",
        sa.Column("inst_id", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("price", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["inst_id"], ["watchlist_items.inst_id"]),
        sa.PrimaryKeyConstraint("inst_id"),
    )


def downgrade() -> None:
    op.drop_table("price_alerts")
    op.drop_index(op.f("ix_watchlist_items_group_name"), table_name="watchlist_items")
    op.drop_table("watchlist_items")
    op.drop_table("watchlists")
    op.drop_index(op.f("ix_instruments_product_key"), table_name="instruments")
    op.drop_index(op.f("ix_instruments_inst_type"), table_name="instruments")
    op.drop_table("instruments")
    op.drop_table("funding")
    op.drop_table("candles")

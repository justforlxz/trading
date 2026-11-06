"""S3 行情与运维表：market 域 + ops 域。

与 `docs/architecture/data-model.md` 的偏差在文档中已注明：
`market.candle` 不建分区（按 bar 差异化保留只能行级删除），并新增
`market.basis_snapshot`（基差可查询）。

Revision ID: 0002_market_ops_schema
Revises: 0001_initial
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_market_ops_schema"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRICE = sa.Numeric(20, 10)
QTY = sa.Numeric(24, 10)
RATIO = sa.Numeric(12, 10)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS market")
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")

    op.create_table(
        "instrument",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("inst_id", sa.Text(), nullable=False, unique=True),
        sa.Column("inst_family", sa.Text(), nullable=False),
        sa.Column("uly", sa.Text(), nullable=False),
        sa.Column("inst_category", sa.SmallInteger(), nullable=False),
        sa.Column("asset_class", sa.Text(), nullable=False),
        sa.Column("exchange", sa.Text()),
        sa.Column("ct_val", PRICE, nullable=False),
        sa.Column("ct_val_ccy", sa.Text(), nullable=False),
        sa.Column("lot_sz", PRICE, nullable=False),
        sa.Column("min_sz", PRICE, nullable=False),
        sa.Column("tick_sz", PRICE, nullable=False),
        sa.Column("lever", PRICE, nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("rule_type", sa.Text(), nullable=False),
        sa.Column("list_time", sa.DateTime(timezone=True)),
        sa.Column(
            "source_synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("raw", postgresql.JSONB(), nullable=False),
        schema="market",
    )

    op.create_table(
        "equity_asset",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("exchange", sa.Text()),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("source_symbol", sa.Text()),
        sa.Column("source_name", sa.Text()),
        sa.Column("mapping_status", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "symbol",
            "exchange",
            name="uq_equity_asset_symbol_exchange",
            postgresql_nulls_not_distinct=True,
        ),
        schema="market",
    )

    op.create_table(
        "candle",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "instrument_id",
            sa.BigInteger(),
            sa.ForeignKey("market.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("bar", sa.Text(), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", PRICE, nullable=False),
        sa.Column("high", PRICE, nullable=False),
        sa.Column("low", PRICE, nullable=False),
        sa.Column("close", PRICE, nullable=False),
        sa.Column("vol", QTY, nullable=False),
        sa.Column("vol_ccy", QTY, nullable=False),
        sa.Column("vol_ccy_quote", QTY, nullable=False),
        sa.Column("confirm", sa.Boolean(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("instrument_id", "bar", "open_time", name="uq_candle_key"),
        schema="market",
    )

    op.create_table(
        "equity_candle",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "equity_asset_id",
            sa.BigInteger(),
            sa.ForeignKey("market.equity_asset.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("interval", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", PRICE, nullable=False),
        sa.Column("high", PRICE, nullable=False),
        sa.Column("low", PRICE, nullable=False),
        sa.Column("close", PRICE, nullable=False),
        sa.Column("volume", QTY, nullable=False),
        sa.Column("session", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("equity_asset_id", "interval", "ts", name="uq_equity_candle_key"),
        schema="market",
    )

    op.create_table(
        "market_session",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("is_session", sa.Boolean(), nullable=False),
        sa.Column("is_half_day", sa.Boolean(), nullable=False),
        sa.Column("is_holiday", sa.Boolean(), nullable=False),
        sa.Column("pre_start", sa.DateTime(timezone=True)),
        sa.Column("pre_end", sa.DateTime(timezone=True)),
        sa.Column("regular_start", sa.DateTime(timezone=True)),
        sa.Column("regular_end", sa.DateTime(timezone=True)),
        sa.Column("post_start", sa.DateTime(timezone=True)),
        sa.Column("post_end", sa.DateTime(timezone=True)),
        sa.Column("calendar_source", sa.Text(), nullable=False),
        sa.Column("calendar_version", sa.Text(), nullable=False),
        sa.UniqueConstraint("venue", "trading_date", name="uq_market_session_key"),
        schema="market",
    )

    op.create_table(
        "data_source_sync",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("dataset", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("coverage", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "source",
            "dataset",
            "scope",
            "window_start",
            "window_end",
            name="uq_data_source_sync",
        ),
        schema="market",
    )

    op.create_table(
        "data_quality_issue",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("dataset", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True)),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "dataset",
            "scope_id",
            "kind",
            "window_start",
            name="uq_data_quality_issue",
        ),
        schema="market",
    )

    op.create_table(
        "basis_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "instrument_id",
            sa.BigInteger(),
            sa.ForeignKey("market.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("okx_price", PRICE, nullable=False),
        sa.Column("equity_price", PRICE, nullable=False),
        sa.Column("basis_bps", sa.Numeric(12, 4), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("instrument_id", "ts", name="uq_basis_snapshot_key"),
        schema="market",
    )

    op.create_table(
        "job_run",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("job_name", sa.Text(), nullable=False),
        sa.Column("job_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("worker", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("job_name", "job_key", name="uq_job_run_key"),
        schema="ops",
    )
    op.create_index("ix_job_run_status", "job_run", ["status"], schema="ops")

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("request_id", sa.Text()),
        sa.Column("actor", sa.Text()),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text()),
        sa.Column("before", postgresql.JSONB()),
        sa.Column("after", postgresql.JSONB()),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("idempotency_key", sa.Text()),
        schema="ops",
    )
    op.create_index(
        "uq_audit_log_idempotency_key",
        "audit_log",
        ["idempotency_key"],
        unique=True,
        schema="ops",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("audit_log", schema="ops")
    op.drop_table("job_run", schema="ops")
    op.drop_table("basis_snapshot", schema="market")
    op.drop_table("data_quality_issue", schema="market")
    op.drop_table("data_source_sync", schema="market")
    op.drop_table("market_session", schema="market")
    op.drop_table("equity_candle", schema="market")
    op.drop_table("candle", schema="market")
    op.drop_table("equity_asset", schema="market")
    op.drop_table("instrument", schema="market")

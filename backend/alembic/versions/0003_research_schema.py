"""S4 研究域：research schema（目标股票、关系快照、关系边、相对强弱快照）。

列与唯一键严格对应 `docs/architecture/data-model.md` §3：
`target_symbol` / `relation_snapshot` / `relation_edge` /
`relative_strength_snapshot`。跨 schema 外键只用到白名单里的
`market.instrument.id`（`adr/0002-single-postgres-schema.md`）。

Revision ID: 0003_research_schema
Revises: 0002_market_ops_schema
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_research_schema"
down_revision: str | None = "0002_market_ops_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RATIO = sa.Numeric(12, 10)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS research")

    op.create_table(
        "target_symbol",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        # 目标股票由用户显式添加，交易所必填；不得用 NULL 表示未知交易所。
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text()),
        sa.Column(
            "instrument_id",
            sa.BigInteger(),
            sa.ForeignKey("market.instrument.id", ondelete="SET NULL"),
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("symbol", "exchange", name="uq_target_symbol_key"),
        schema="research",
    )
    op.create_index("ix_target_symbol_enabled", "target_symbol", ["enabled"], schema="research")

    op.create_table(
        "relation_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "target_id",
            sa.BigInteger(),
            sa.ForeignKey("research.target_symbol.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_bars", sa.Integer(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("price_basis", sa.Text(), nullable=False),
        sa.Column("lag_max", sa.Integer(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("run_key", sa.Text(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("run_key", name="uq_relation_snapshot_run_key"),
        sa.UniqueConstraint(
            "target_id",
            "as_of",
            "window_bars",
            "method",
            "price_basis",
            name="uq_relation_snapshot_business",
        ),
        schema="research",
    )
    op.create_index(
        "ix_relation_snapshot_target_as_of",
        "relation_snapshot",
        ["target_id", "as_of"],
        schema="research",
    )

    op.create_table(
        "relation_edge",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.BigInteger(),
            sa.ForeignKey("research.relation_snapshot.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "counterparty_id",
            sa.BigInteger(),
            sa.ForeignKey("market.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("coefficient", RATIO, nullable=False),
        sa.Column("best_lag", sa.Integer(), nullable=False),
        sa.Column("p_value", RATIO),
        sa.Column("stability", RATIO),
        sa.Column("rank", sa.Integer(), nullable=False),
        # 不同 lag 是不同边，因此 best_lag 属于唯一键。
        sa.UniqueConstraint(
            "snapshot_id", "counterparty_id", "best_lag", name="uq_relation_edge_key"
        ),
        schema="research",
    )

    op.create_table(
        "relative_strength_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "target_id",
            sa.BigInteger(),
            sa.ForeignKey("research.target_symbol.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "counterparty_id",
            sa.BigInteger(),
            sa.ForeignKey("market.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lookback_bars", sa.Integer(), nullable=False),
        sa.Column("rs_ratio", RATIO, nullable=False),
        sa.Column("rs_momentum", RATIO, nullable=False),
        sa.Column("run_key", sa.Text(), nullable=False),
        sa.UniqueConstraint("run_key", name="uq_relative_strength_snapshot_run_key"),
        schema="research",
    )
    op.create_index(
        "ix_relative_strength_snapshot_target",
        "relative_strength_snapshot",
        ["target_id", "counterparty_id"],
        schema="research",
    )


def downgrade() -> None:
    op.drop_table("relative_strength_snapshot", schema="research")
    op.drop_table("relation_edge", schema="research")
    op.drop_table("relation_snapshot", schema="research")
    op.drop_index("ix_target_symbol_enabled", table_name="target_symbol", schema="research")
    op.drop_table("target_symbol", schema="research")
    op.execute("DROP SCHEMA IF EXISTS research")

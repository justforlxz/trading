"""S5 机会发现：opportunity schema 与 research.market_snapshot。

列与唯一键严格对应 `docs/architecture/data-model.md`：
§3 的 `market_snapshot`（全市场特征截面，落在 research schema），
§4 的 `opportunity_run` / `opportunity` / `asset_cluster` / `cluster_member`。

跨 schema 外键只用到白名单里的 `market.instrument.id`
（`adr/0002-single-postgres-schema.md`）。

Revision ID: 0004_opportunity_schema
Revises: 0003_research_schema
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_opportunity_schema"
down_revision: str | None = "0003_research_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RATIO = sa.Numeric(12, 10)
PRICE = sa.Numeric(20, 10)
SCORE = sa.Numeric(12, 10)


def upgrade() -> None:
    # §3：截面特征表属于 research schema；run_id 只做溯源，不进唯一键。
    op.create_table(
        "market_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.BigInteger()),
        sa.Column(
            "instrument_id",
            sa.BigInteger(),
            sa.ForeignKey("market.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ret_1d", RATIO),
        sa.Column("ret_5d", RATIO),
        sa.Column("ret_20d", RATIO),
        sa.Column("vol_20d", RATIO),
        sa.Column("atr_14", PRICE),
        sa.Column("volume_z", RATIO),
        sa.Column("high_20d", PRICE),
        sa.Column("low_20d", PRICE),
        sa.Column("extras", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.UniqueConstraint("as_of", "instrument_id", name="uq_market_snapshot_key"),
        schema="research",
    )
    op.create_index("ix_market_snapshot_as_of", "market_snapshot", ["as_of"], schema="research")

    op.execute("CREATE SCHEMA IF NOT EXISTS opportunity")

    op.create_table(
        "opportunity_run",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("run_key", sa.Text(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("universe_size", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'running'")),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column("counts", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
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
        sa.UniqueConstraint("run_key", name="uq_opportunity_run_key"),
        schema="opportunity",
    )
    op.create_index("ix_opportunity_run_as_of", "opportunity_run", ["as_of"], schema="opportunity")

    op.create_table(
        "asset_cluster",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("opportunity.opportunity_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False, server_default=sa.text("'hierarchical'")),
        sa.Column("silhouette", RATIO),
        sa.Column("size", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("centroid", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("run_id", "label", name="uq_asset_cluster_label"),
        schema="opportunity",
    )

    op.create_table(
        "cluster_member",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "cluster_id",
            sa.BigInteger(),
            sa.ForeignKey("opportunity.asset_cluster.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "instrument_id",
            sa.BigInteger(),
            sa.ForeignKey("market.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("distance", RATIO, nullable=False, server_default=sa.text("0")),
        sa.Column("weight", RATIO, nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint("cluster_id", "instrument_id", name="uq_cluster_member_key"),
        schema="opportunity",
    )
    op.create_index(
        "ix_cluster_member_instrument",
        "cluster_member",
        ["instrument_id"],
        schema="opportunity",
    )

    op.create_table(
        "opportunity",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("opportunity.opportunity_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "primary_instrument_id",
            sa.BigInteger(),
            sa.ForeignKey("market.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("score", SCORE, nullable=False),
        sa.Column("horizon", sa.Text(), nullable=False),
        sa.Column("reasons", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("run_id", "dedupe_key", name="uq_opportunity_dedupe"),
        schema="opportunity",
    )
    op.create_index(
        "ix_opportunity_run_score", "opportunity", ["run_id", "score"], schema="opportunity"
    )


def downgrade() -> None:
    op.drop_index("ix_opportunity_run_score", table_name="opportunity", schema="opportunity")
    op.drop_table("opportunity", schema="opportunity")
    op.drop_index("ix_cluster_member_instrument", table_name="cluster_member", schema="opportunity")
    op.drop_table("cluster_member", schema="opportunity")
    op.drop_table("asset_cluster", schema="opportunity")
    op.drop_index("ix_opportunity_run_as_of", table_name="opportunity_run", schema="opportunity")
    op.drop_table("opportunity_run", schema="opportunity")
    op.execute("DROP SCHEMA IF EXISTS opportunity")

    op.drop_index("ix_market_snapshot_as_of", table_name="market_snapshot", schema="research")
    op.drop_table("market_snapshot", schema="research")

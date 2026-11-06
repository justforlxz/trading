"""S6 策略：strategy schema（策略头、策略腿、审批与状态迁移审计）。

列与唯一键严格对应 `docs/architecture/data-model.md` §5：
`strategy` / `strategy_leg` / `strategy_approval` / `strategy_transition`。

跨 schema 外键只用到白名单里的 `market.instrument.id` 与
`research.target_symbol.id`（`adr/0002-single-postgres-schema.md`），
不改动 market/research/opportunity 既有表。

Revision ID: 0005_strategy_schema
Revises: 0004_opportunity_schema
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_strategy_schema"
down_revision: str | None = "0004_opportunity_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WEIGHT = sa.Numeric(12, 10)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS strategy")

    op.create_table(
        "strategy",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("strategy_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column(
            "target_id",
            sa.BigInteger(),
            sa.ForeignKey("research.target_symbol.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "templates", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "params", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
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
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("strategy_key", name="uq_strategy_key"),
        sa.UniqueConstraint("id", "version", name="uq_strategy_version"),
        schema="strategy",
    )

    op.create_table(
        "strategy_leg",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "strategy_id",
            sa.BigInteger(),
            sa.ForeignKey("strategy.strategy.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "instrument_id",
            sa.BigInteger(),
            sa.ForeignKey("market.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("target_weight", WEIGHT, nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("strategy_id", "instrument_id", name="uq_strategy_leg_member"),
        schema="strategy",
    )

    op.create_table(
        "strategy_approval",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "strategy_id",
            sa.BigInteger(),
            sa.ForeignKey("strategy.strategy.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.Text(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "strategy_id", "content_hash", "decision", name="uq_strategy_approval_key"
        ),
        schema="strategy",
    )

    op.create_table(
        "strategy_transition",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "strategy_id",
            sa.BigInteger(),
            sa.ForeignKey("strategy.strategy.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_status", sa.Text(), nullable=False),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("request_id", sa.Text()),
        schema="strategy",
    )
    op.create_index(
        "ix_strategy_transition_at",
        "strategy_transition",
        ["strategy_id", "at"],
        schema="strategy",
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_transition_at", table_name="strategy_transition", schema="strategy")
    op.drop_table("strategy_transition", schema="strategy")
    op.drop_table("strategy_approval", schema="strategy")
    op.drop_table("strategy_leg", schema="strategy")
    op.drop_table("strategy", schema="strategy")
    op.execute("DROP SCHEMA IF EXISTS strategy")

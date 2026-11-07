"""risk schema

Revision ID: 0007_risk_schema
Revises: 0006_backtest_schema
Create Date: 2026-11-07

P2 风控：策略级与全局组合风控阈值策略以及风险事件。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_risk_schema"
down_revision = "0006_backtest_schema"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(24, 10)
RATIO = sa.Numeric(12, 10)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS risk")

    op.create_table(
        "risk_policy",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column(
            "strategy_id",
            sa.BigInteger,
            sa.ForeignKey("strategy.strategy.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("max_order_notional", MONEY, nullable=False),
        sa.Column("max_leg_weight", RATIO, nullable=False),
        sa.Column("max_leverage", RATIO, nullable=False),
        sa.Column("max_gross_exposure", RATIO, nullable=False),
        sa.Column("max_net_exposure", RATIO, nullable=False),
        sa.Column("max_instrument_weight", RATIO, nullable=False),
        sa.Column("max_concentration", RATIO, nullable=False),
        sa.Column("drawdown_warn", RATIO, nullable=False),
        sa.Column("drawdown_reduce", RATIO, nullable=False),
        sa.Column("drawdown_close", RATIO, nullable=False),
        sa.Column("funding_rate_threshold", RATIO, nullable=False),
        sa.Column("min_depth_notional", MONEY, nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("updated_by", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "scope",
            "strategy_id",
            "version",
            name="uq_risk_policy_version",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint(
            "(scope = 'global' AND strategy_id IS NULL)"
            " OR (scope = 'strategy' AND strategy_id IS NOT NULL)",
            name="ck_risk_policy_scope",
        ),
        schema="risk",
    )

    op.create_table(
        "risk_event",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column(
            "strategy_id",
            sa.BigInteger,
            sa.ForeignKey("strategy.strategy.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "instrument_id",
            sa.BigInteger,
            sa.ForeignKey("market.instrument.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("policy_version", sa.Integer, nullable=False),
        sa.Column("observed_value", MONEY, nullable=True),
        sa.Column("threshold", MONEY, nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("evaluation_key", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "kind",
            "strategy_id",
            "instrument_id",
            "policy_version",
            "evaluation_key",
            name="uq_risk_event_key",
            postgresql_nulls_not_distinct=True,
        ),
        schema="risk",
    )
    op.create_index("ix_risk_event_created_at", "risk_event", ["created_at"], schema="risk")


def downgrade() -> None:
    op.drop_index("ix_risk_event_created_at", table_name="risk_event", schema="risk")
    op.drop_table("risk_event", schema="risk")
    op.drop_table("risk_policy", schema="risk")
    op.execute("DROP SCHEMA IF EXISTS risk")


__all__ = ["downgrade", "revision", "upgrade"]

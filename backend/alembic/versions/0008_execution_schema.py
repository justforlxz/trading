"""execution schema（P3 交易执行）。

新增四张表：订单、成交、策略级虚拟持仓、对账差异。订单表用 `"order"` 这个
保留字作为表名（data-model §9 的既定命名），由 SQLAlchemy 自动加引号。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_execution_schema"
down_revision = "0007_risk_schema"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(24, 10)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS execution")

    op.create_table(
        "order",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("client_order_id", sa.Text, nullable=False),
        sa.Column("exchange_order_id", sa.Text, nullable=True),
        sa.Column("mode", sa.Text, nullable=False),
        sa.Column(
            "strategy_id",
            sa.BigInteger,
            sa.ForeignKey("strategy.strategy.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "instrument_id",
            sa.BigInteger,
            sa.ForeignKey("market.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("inst_id", sa.Text, nullable=False),
        sa.Column("side", sa.Text, nullable=False),
        sa.Column("position_side", sa.Text, nullable=False),
        sa.Column("order_type", sa.Text, nullable=False),
        sa.Column("quantity", MONEY, nullable=False),
        sa.Column("price", MONEY, nullable=True),
        sa.Column("reduce_only", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("intent", sa.Text, nullable=False, server_default=sa.text("'entry'")),
        sa.Column("state", sa.Text, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("filled_quantity", MONEY, nullable=False, server_default=sa.text("0")),
        sa.Column("average_price", MONEY, nullable=True),
        sa.Column("fee", MONEY, nullable=False, server_default=sa.text("0")),
        sa.Column("reject_reason", sa.Text, nullable=True),
        sa.Column(
            "risk_event_id",
            sa.BigInteger,
            sa.ForeignKey("risk.risk_event.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("client_order_id", name="uq_execution_order_client_id"),
        sa.CheckConstraint(
            "state IN ('pending','submitted','partial','filled','canceled','rejected')",
            name="ck_execution_order_state",
        ),
        sa.CheckConstraint("mode IN ('paper','real')", name="ck_execution_order_mode"),
        sa.CheckConstraint("side IN ('buy','sell')", name="ck_execution_order_side"),
        sa.CheckConstraint(
            "position_side IN ('long','short')", name="ck_execution_order_position_side"
        ),
        sa.CheckConstraint("order_type IN ('market','limit')", name="ck_execution_order_type"),
        sa.CheckConstraint("intent IN ('entry','exit','stop')", name="ck_execution_order_intent"),
        sa.CheckConstraint("quantity > 0", name="ck_execution_order_quantity"),
        sa.CheckConstraint(
            "filled_quantity >= 0 AND filled_quantity <= quantity",
            name="ck_execution_order_filled",
        ),
        schema="execution",
    )
    op.create_index("ix_execution_order_state", "order", ["state"], schema="execution")
    op.create_index(
        "ix_execution_order_strategy", "order", ["strategy_id", "created_at"], schema="execution"
    )

    op.create_table(
        "fill",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "order_id",
            sa.BigInteger,
            sa.ForeignKey("execution.order.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fill_id", sa.Text, nullable=False),
        sa.Column(
            "strategy_id",
            sa.BigInteger,
            sa.ForeignKey("strategy.strategy.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "instrument_id",
            sa.BigInteger,
            sa.ForeignKey("market.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("inst_id", sa.Text, nullable=False),
        sa.Column("side", sa.Text, nullable=False),
        sa.Column("position_side", sa.Text, nullable=False),
        sa.Column("quantity", MONEY, nullable=False),
        sa.Column("price", MONEY, nullable=False),
        sa.Column("fee", MONEY, nullable=False, server_default=sa.text("0")),
        sa.Column("realized_pnl", MONEY, nullable=False, server_default=sa.text("0")),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("order_id", "fill_id", name="uq_execution_fill_key"),
        schema="execution",
    )
    op.create_index("ix_execution_fill_filled_at", "fill", ["filled_at"], schema="execution")

    op.create_table(
        "position",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "strategy_id",
            sa.BigInteger,
            sa.ForeignKey("strategy.strategy.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "instrument_id",
            sa.BigInteger,
            sa.ForeignKey("market.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("inst_id", sa.Text, nullable=False),
        sa.Column("position_side", sa.Text, nullable=False),
        sa.Column("quantity", MONEY, nullable=False, server_default=sa.text("0")),
        sa.Column("average_price", MONEY, nullable=False, server_default=sa.text("0")),
        sa.Column("realized_pnl", MONEY, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "strategy_id",
            "instrument_id",
            "position_side",
            name="uq_execution_position_key",
        ),
        sa.CheckConstraint("position_side IN ('long','short')", name="ck_execution_position_side"),
        sa.CheckConstraint("quantity >= 0", name="ck_execution_position_quantity"),
        schema="execution",
    )

    op.create_table(
        "reconcile_diff",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
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
        sa.Column("inst_id", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("position_side", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("reference", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("local_value", MONEY, nullable=True),
        sa.Column("exchange_value", MONEY, nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'open'")),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Text, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("resolve_attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("status IN ('open','resolved')", name="ck_execution_reconcile_status"),
        schema="execution",
    )
    op.create_index(
        "uq_execution_reconcile_open",
        "reconcile_diff",
        ["kind", "inst_id", "position_side", "reference"],
        unique=True,
        schema="execution",
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_execution_reconcile_status",
        "reconcile_diff",
        ["status", "detected_at"],
        schema="execution",
    )


def downgrade() -> None:
    op.drop_index("ix_execution_reconcile_status", table_name="reconcile_diff", schema="execution")
    op.drop_index("uq_execution_reconcile_open", table_name="reconcile_diff", schema="execution")
    op.drop_table("reconcile_diff", schema="execution")
    op.drop_table("position", schema="execution")
    op.drop_index("ix_execution_fill_filled_at", table_name="fill", schema="execution")
    op.drop_table("fill", schema="execution")
    op.drop_index("ix_execution_order_strategy", table_name="order", schema="execution")
    op.drop_index("ix_execution_order_state", table_name="order", schema="execution")
    op.drop_table("order", schema="execution")
    op.execute("DROP SCHEMA IF EXISTS execution")


__all__ = ["downgrade", "revision", "upgrade"]

"""账户与持仓：OKX 只读快照、手动持仓、流水与本地风控配置。

五张新表：

- `account_snapshots`：账户权益快照，唯一键 `(account_id, captured_at, source)`；
- `exchange_position_snapshots`：交易所持仓快照，唯一键
  `(account_id, pos_id, captured_at)`；
- `manual_positions`：本地手动持仓的当前状态；
- `manual_trades`：只追加的手动流水，`idempotency_key` 唯一；
- `position_risk_config`：按持仓引用保存的本地止损与预警阈值。

同时给 `instruments` 增加可空列 `sector`，供后续风险域计算行业敞口。

迁移脚本不导入应用代码。

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False, server_default="okx-main"),
        sa.Column("currency", sa.String(length=16), nullable=False, server_default="USDT"),
        sa.Column("equity", sa.String(length=64), nullable=False),
        sa.Column("available_equity", sa.String(length=64), nullable=False),
        sa.Column("cash_balance", sa.String(length=64), nullable=False),
        sa.Column("unrealized_pnl", sa.String(length=64), nullable=False),
        sa.Column("used_margin", sa.String(length=64), nullable=False),
        sa.Column("available_margin", sa.String(length=64), nullable=False),
        sa.Column("margin_ratio", sa.String(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("raw_payload_ref", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "captured_at", "source"),
    )

    op.create_table(
        "exchange_position_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False, server_default="okx-main"),
        sa.Column("pos_id", sa.String(length=96), nullable=False),
        sa.Column("inst_id", sa.String(length=64), nullable=False),
        sa.Column("pos_side", sa.String(length=8), nullable=False),
        sa.Column("size", sa.String(length=64), nullable=False),
        sa.Column("avg_px", sa.String(length=64), nullable=False),
        sa.Column("mark_px", sa.String(length=64), nullable=True),
        sa.Column("upl", sa.String(length=64), nullable=True),
        sa.Column("upl_ratio", sa.String(length=64), nullable=True),
        sa.Column("lever", sa.String(length=64), nullable=True),
        sa.Column("mgn_mode", sa.String(length=16), nullable=True),
        sa.Column("liq_px", sa.String(length=64), nullable=True),
        sa.Column("margin", sa.String(length=64), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "pos_id", "captured_at"),
    )
    op.create_index(
        "ix_exchange_position_snapshots_account_captured",
        "exchange_position_snapshots",
        ["account_id", "captured_at"],
        unique=False,
    )

    op.create_table(
        "manual_positions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("inst_id", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.String(length=64), nullable=False),
        sa.Column("avg_cost", sa.String(length=64), nullable=False),
        sa.Column("stop_px", sa.String(length=64), nullable=True),
        sa.Column("leverage", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_manual_positions_inst_id", "manual_positions", ["inst_id"], unique=False)

    op.create_table(
        "manual_trades",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("position_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.String(length=64), nullable=False),
        sa.Column("price", sa.String(length=64), nullable=False),
        sa.Column("fee", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["position_id"], ["manual_positions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_manual_trades_position_id", "manual_trades", ["position_id"], unique=False)

    op.create_table(
        "position_risk_config",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("position_ref", sa.String(length=128), nullable=False),
        sa.Column("stop_px", sa.String(length=64), nullable=True),
        sa.Column("risk_budget", sa.String(length=64), nullable=True),
        sa.Column("warning_threshold_pct", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("position_ref"),
    )

    op.add_column("instruments", sa.Column("sector", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("instruments", "sector")
    op.drop_table("position_risk_config")
    op.drop_index("ix_manual_trades_position_id", table_name="manual_trades")
    op.drop_table("manual_trades")
    op.drop_index("ix_manual_positions_inst_id", table_name="manual_positions")
    op.drop_table("manual_positions")
    op.drop_index(
        "ix_exchange_position_snapshots_account_captured",
        table_name="exchange_position_snapshots",
    )
    op.drop_table("exchange_position_snapshots")
    op.drop_table("account_snapshots")

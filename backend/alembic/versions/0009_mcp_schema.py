"""mcp schema（P4 MCP 服务）。

新增三部分：

1. `mcp.client`：外部 Agent 客户端（只存 token 的 sha256）。
2. `mcp.call_log`：每次 MCP 调用的审计记录（操作类带 `reason`）。
3. `strategy.strategy.paused_at`：策略运行暂停标记。

第 3 项不引入新的策略状态机：暂停/恢复只写一个时刻列，`status` 仍是
`docs/architecture/data-model.md` 定义的五个值；MCP 的 `execute_strategy_action`
把它作为「策略未暂停」闸门的判据。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_mcp_schema"
down_revision = "0008_execution_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS mcp")

    op.create_table(
        "mcp_clients",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False),
        sa.Column(
            "scopes",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_mcp_clients_token_hash"),
        schema="mcp",
    )

    op.create_table(
        "mcp_call_log",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "client_id",
            sa.BigInteger,
            sa.ForeignKey("mcp.mcp_clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool", sa.Text, nullable=False),
        sa.Column("args_digest", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("error_code", sa.Text, nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="mcp",
    )
    op.create_index("ix_mcp_call_log_created_at", "mcp_call_log", ["created_at"], schema="mcp")
    op.create_index(
        "ix_mcp_call_log_client", "mcp_call_log", ["client_id", "created_at"], schema="mcp"
    )

    op.add_column(
        "strategy",
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        schema="strategy",
    )


def downgrade() -> None:
    op.drop_column("strategy", "paused_at", schema="strategy")
    op.drop_index("ix_mcp_call_log_client", table_name="mcp_call_log", schema="mcp")
    op.drop_index("ix_mcp_call_log_created_at", table_name="mcp_call_log", schema="mcp")
    op.drop_table("mcp_call_log", schema="mcp")
    op.drop_table("mcp_clients", schema="mcp")
    op.execute("DROP SCHEMA IF EXISTS mcp")


__all__ = ["downgrade", "revision", "upgrade"]

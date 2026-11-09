"""mcp schema 的 ORM 模型：客户端与服务调用审计。

Token 只在创建时明文返回一次，本表只存 sha256；吊销即写 `revoked_at`，
行保留以便审计日志仍能追溯到具体客户端。
"""

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SCHEMA = "mcp"

SCOPE_READ = "read"
SCOPE_OPERATE = "operate"
SCOPES = (SCOPE_READ, SCOPE_OPERATE)


class McpClient(Base):
    """一个外部 Agent 客户端；`token_hash` 唯一，是鉴权的唯一依据。"""

    __tablename__ = "mcp_clients"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("token_hash", name="uq_mcp_clients_token_hash"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class McpCallLog(Base):
    """一次 MCP 调用；操作类调用必须留 `reason`，否则无法解释外部 Agent 的动机。"""

    __tablename__ = "mcp_call_log"
    __table_args__: ClassVar[Any] = (
        Index("ix_mcp_call_log_created_at", "created_at"),
        Index("ix_mcp_call_log_client", "client_id", "created_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{SCHEMA}.mcp_clients.id", ondelete="CASCADE"), nullable=False
    )
    tool: Mapped[str] = mapped_column(Text, nullable=False)
    args_digest: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["SCHEMA", "SCOPES", "SCOPE_OPERATE", "SCOPE_READ", "McpCallLog", "McpClient"]

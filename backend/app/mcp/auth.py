"""MCP 客户端鉴权（纯 hash 比较 + scope 判定）。

Token 只在创建时明文返回一次；库里只存 `sha256(token)`。因此这里不存在
「取出明文再比较」的路径，泄露数据库也拿不到可用 token。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.models import SCOPE_OPERATE, SCOPE_READ, SCOPES, McpClient

TOKEN_BYTES = 32
CODE_UNAUTHORIZED = "mcp_unauthorized"
CODE_FORBIDDEN = "mcp_forbidden"


class McpAuthError(Exception):
    """鉴权/授权失败；`status_code` 直接用作 HTTP 状态。"""

    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def bearer_token(authorization: str | None) -> str:
    """从 `Authorization: Bearer <token>` 取出 token；缺失或格式不对即未授权。"""

    if not authorization:
        raise McpAuthError(CODE_UNAUTHORIZED, "missing bearer token", status_code=401)
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise McpAuthError(CODE_UNAUTHORIZED, "invalid authorization header", status_code=401)
    return value.strip()


async def find_client(session: AsyncSession, token: str) -> McpClient:
    """按 token 找未吊销的客户端；更新 `last_used_at`（只写这一列）。"""

    client = (
        await session.execute(select(McpClient).where(McpClient.token_hash == hash_token(token)))
    ).scalar_one_or_none()
    if client is None or client.revoked_at is not None:
        raise McpAuthError(CODE_UNAUTHORIZED, "unknown or revoked token", status_code=401)
    # 只写这一列：直接赋值而不是 bulk UPDATE，避免同步策略把身份映射里的客户端
    # 对象标记过期（之后读属性会触发同步 IO，在 async 会话里是致命错误）。
    client.last_used_at = datetime.now(tz=UTC)
    await session.commit()
    return client


def client_scopes(client: McpClient) -> frozenset[str]:
    raw = client.scopes or []
    return frozenset(item for item in raw if isinstance(item, str) and item in SCOPES)


def require_scope(client: McpClient, required: str) -> None:
    """`operate` 覆盖 `read`；`read` 客户端调操作类工具一律 403。"""

    held = client_scopes(client)
    if required == SCOPE_READ and held & {SCOPE_READ, SCOPE_OPERATE}:
        return
    if required == SCOPE_OPERATE and SCOPE_OPERATE in held:
        return
    raise McpAuthError(
        CODE_FORBIDDEN,
        f"client {client.name!r} lacks scope {required}",
        status_code=403,
    )


__all__ = [
    "CODE_FORBIDDEN",
    "CODE_UNAUTHORIZED",
    "McpAuthError",
    "bearer_token",
    "client_scopes",
    "find_client",
    "hash_token",
    "new_token",
    "require_scope",
]

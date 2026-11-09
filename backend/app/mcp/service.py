"""MCP 客户端管理：生成、列出、吊销。

明文 token 只在 `create_client` 的返回值里出现一次，之后任何读路径都拿不到；
列表接口只给出 scope、创建时间、最近调用时间与吊销状态。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.auth import hash_token, new_token
from app.mcp.models import SCOPE_OPERATE, SCOPE_READ, SCOPES, McpClient


class InvalidScopes(ValueError):
    """scope 列表为空或含未知值。"""


class ClientNotFound(LookupError):
    """客户端 id 不存在。"""


def normalize_scopes(values: list[str]) -> list[str]:
    """去重并按 read -> operate 的固定顺序落库，重复输入不改变语义。"""

    unknown = sorted({value for value in values if value not in SCOPES})
    if unknown:
        raise InvalidScopes(f"unknown scopes: {', '.join(unknown)}")
    ordered = [scope for scope in (SCOPE_READ, SCOPE_OPERATE) if scope in set(values)]
    if not ordered:
        raise InvalidScopes("at least one scope is required")
    return ordered


def client_payload(client: McpClient) -> dict[str, Any]:
    return {
        "id": client.id,
        "name": client.name,
        "scopes": list(client.scopes or []),
        "created_at": _iso(client.created_at),
        "last_used_at": _iso(client.last_used_at),
        "revoked_at": _iso(client.revoked_at),
        "revoked": client.revoked_at is not None,
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


async def create_client(
    session: AsyncSession, *, name: str, scopes: list[str]
) -> tuple[McpClient, str]:
    """建客户端并返回 `(行, 明文 token)`；明文不再保存。"""

    token = new_token()
    client = McpClient(name=name, token_hash=hash_token(token), scopes=normalize_scopes(scopes))
    session.add(client)
    await session.commit()
    await session.refresh(client)
    return client, token


async def list_clients(session: AsyncSession, *, limit: int = 200) -> list[McpClient]:
    statement = select(McpClient).order_by(McpClient.id.desc()).limit(limit)
    return list(await session.scalars(statement))


async def get_client(session: AsyncSession, client_id: int) -> McpClient:
    client = await session.get(McpClient, client_id)
    if client is None:
        raise ClientNotFound(f"unknown mcp client: {client_id}")
    return client


async def revoke_client(session: AsyncSession, client_id: int) -> McpClient:
    """吊销：只写 `revoked_at`，行保留以便审计追溯；重复吊销幂等。"""

    client = await get_client(session, client_id)
    if client.revoked_at is None:
        client.revoked_at = datetime.now(tz=UTC)
        await session.commit()
        await session.refresh(client)
    return client


__all__ = [
    "ClientNotFound",
    "InvalidScopes",
    "client_payload",
    "create_client",
    "get_client",
    "list_clients",
    "normalize_scopes",
    "revoke_client",
]

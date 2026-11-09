"""`/api/v1/mcp/clients`：MCP 客户端管理（Web「设置」页用）。

生成时明文 token 只返回这一次；列表与吊销都不回显 token。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.v1.deps import session_dep
from app.mcp import service

router = APIRouter(prefix="/mcp", tags=["mcp"])
SessionDep = Annotated[AsyncSession, Depends(session_dep)]

MAX_LIMIT = 200


class CreateClientRequest(BaseModel):
    """创建一个 MCP 客户端；scope 只允许 read / operate。"""

    name: str = Field(min_length=1, max_length=100)
    scopes: list[Literal["read", "operate"]] = Field(min_length=1)


@router.get("/clients")
async def list_clients(session: SessionDep, limit: int = MAX_LIMIT) -> dict[str, Any]:
    rows = await service.list_clients(session, limit=min(limit, MAX_LIMIT))
    return {"items": [service.client_payload(row) for row in rows]}


@router.post("/clients", status_code=status.HTTP_201_CREATED)
async def create_client(payload: CreateClientRequest, session: SessionDep) -> dict[str, Any]:
    """返回 `{client, token}`；`token` 之后无法再取回。"""

    try:
        client, token = await service.create_client(
            session, name=payload.name, scopes=list(payload.scopes)
        )
    except service.InvalidScopes as error:
        raise ApiError("mcp_invalid_scopes", str(error), status_code=422) from error
    return {"client": service.client_payload(client), "token": token}


@router.delete("/clients/{client_id}")
async def revoke_client(client_id: int, session: SessionDep) -> dict[str, Any]:
    try:
        client = await service.revoke_client(session, client_id)
    except service.ClientNotFound as error:
        raise ApiError(
            "mcp_client_not_found",
            str(error),
            status_code=404,
            details={"client_id": client_id},
        ) from error
    return service.client_payload(client)


__all__ = ["router"]

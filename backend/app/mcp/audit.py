"""MCP 调用审计：每次调用写一条 `mcp.call_log`。

写日志本身失败不应该让业务调用变成 500（审计不改变业务结论），因此这里
回滚并记录一条警告；调用结果仍按业务层已产生的事实返回。
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.models import McpCallLog, McpClient

logger = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_DENIED = "denied"


def args_digest(arguments: Any) -> str:
    """参数摘要：稳定排序的 JSON 再 sha256，长短参数都不落明文。"""

    if arguments is None:
        payload = ""
    else:
        try:
            payload = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
        except (TypeError, ValueError):  # pragma: no cover - 参数已由 JSON 解析得到
            payload = repr(arguments)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def record_call(
    session: AsyncSession,
    *,
    client: McpClient,
    tool: str,
    arguments: Any,
    status: str,
    error_code: str | None = None,
    reason: str | None = None,
    latency_ms: int = 0,
) -> None:
    session.add(
        McpCallLog(
            client_id=client.id,
            tool=tool,
            args_digest=args_digest(arguments),
            status=status,
            error_code=error_code,
            reason=reason,
            latency_ms=latency_ms,
        )
    )
    try:
        await session.commit()
    except SQLAlchemyError:  # pragma: no cover - 环境故障
        await session.rollback()
        logger.warning("mcp audit write failed: tool=%s status=%s", tool, status)


__all__ = [
    "STATUS_DENIED",
    "STATUS_ERROR",
    "STATUS_OK",
    "args_digest",
    "record_call",
]

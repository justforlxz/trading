"""助手调用审计: 复用 `ops.audit_log`, 不新增迁移。

每条记录: `actor='ai'`、`action='ai.<verb>'`、`resource/resource_id` 指向被解释实体,
`after` 记录模型、耗时、token 与结果 (ok / forbidden / not_found / error) 。
`idempotency_key` 由请求 id 派生, 同一请求重复写入只保留一条。

审计是 `app.ai` **唯一**允许的写入, 也是 `app.ai` 唯一碰数据库的地方。为了守住
`app.ai` 的 import 白名单 (见 api-contract §4), 这里用 SQLAlchemy Core 直接写
`ops.audit_log`, 不 import `app.ops.models`; 列定义与 `AuditLog` 模型一一对应。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import BigInteger, Column, DateTime, MetaData, Table, Text, func
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.db.session import AsyncSession

logger = logging.getLogger(__name__)

ACTOR = "ai"

OUTCOME_OK = "ok"
OUTCOME_FORBIDDEN = "forbidden"
OUTCOME_REFUSED = "refused"
OUTCOME_NOT_FOUND = "not_found"
OUTCOME_ERROR = "error"

# 与 `app.ops.models.AuditLog` 同表同列; 只用于 insert。
AUDIT_LOG = Table(
    "audit_log",
    MetaData(),
    Column("id", BigInteger, primary_key=True),
    Column("request_id", Text),
    Column("actor", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("resource", Text, nullable=False),
    Column("resource_id", Text),
    Column("before", JSONB),
    Column("after", JSONB),
    Column("at", DateTime(timezone=True), server_default=func.now()),
    Column("idempotency_key", Text),
    schema="ops",
)


def idempotency_key_for(action: str, request_id: str | None) -> str | None:
    if not request_id:
        return None
    return f"ai:{action}:{request_id}"


async def record(
    session: AsyncSession,
    *,
    request_id: str | None,
    action: str,
    resource: str,
    resource_id: str | int | None,
    model: dict[str, Any],
    latency_ms: int,
    outcome: str,
    tokens: int | None = None,
) -> bool:
    """写一条审计; 返回是否真的落库 (幂等冲突或存储失败返回 False) 。"""

    after: dict[str, Any] = {
        "model": model,
        "latency_ms": latency_ms,
        "outcome": outcome,
    }
    if tokens is not None:
        after["tokens"] = tokens
    statement = insert(AUDIT_LOG).values(
        request_id=request_id,
        actor=ACTOR,
        action=action,
        resource=resource,
        resource_id=None if resource_id is None else str(resource_id),
        after=after,
        idempotency_key=idempotency_key_for(action, request_id),
    )
    try:
        async with session.begin_nested():
            await session.execute(statement)
        await session.commit()
        return True
    except IntegrityError:
        # 同一 idempotency_key 已存在: 静默保留首条。
        await session.rollback()
        return False
    except SQLAlchemyError:
        await session.rollback()
        logger.exception("failed to write ai audit log action=%s", action)
        return False


__all__ = [
    "ACTOR",
    "AUDIT_LOG",
    "OUTCOME_ERROR",
    "OUTCOME_FORBIDDEN",
    "OUTCOME_NOT_FOUND",
    "OUTCOME_OK",
    "OUTCOME_REFUSED",
    "idempotency_key_for",
    "record",
]

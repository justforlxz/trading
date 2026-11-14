"""活动流水的写入与读取。

写入方在业务动作的同一个事务里调用 `record_activity(..., session=session)`，活动与
业务事实一起提交或一起回滚；没有外部事务时才由本模块自己开一个工作单元。
读取按时间倒序，游标是「创建时刻 + 标识」，同一秒内也能稳定翻页。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activity.model import ActivityEventRow
from app.core import Clock, SystemClock, ValidationError
from app.db import session_scope

__all__ = ["ActivityRecord", "list_activity", "record_activity"]

MAX_LIMIT = 200


@dataclass(frozen=True, slots=True)
class ActivityRecord:
    """一条活动流水的只读视图。"""

    id: str
    event_type: str
    object_type: str
    object_id: str
    summary: str
    payload: Mapping[str, object]
    created_at: datetime


def record_activity(
    *,
    event_type: str,
    object_type: str,
    object_id: str,
    summary: str,
    payload: Mapping[str, object] | None = None,
    session: Session | None = None,
    clock: Clock | None = None,
) -> ActivityRecord:
    """追加一条活动；传入 `session` 时使用调用方的事务。"""

    for name, value in (
        ("event_type", event_type),
        ("object_type", object_type),
        ("object_id", object_id),
        ("summary", summary),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"活动的 {name} 不能为空")

    moment = (clock or SystemClock()).now()
    body = dict(payload or {})
    row = ActivityEventRow(
        id="ac_" + uuid4().hex[:24],
        event_type=event_type.strip(),
        object_type=object_type.strip(),
        object_id=object_id.strip(),
        summary=summary.strip(),
        payload_json=json.dumps(body, ensure_ascii=False, sort_keys=True, default=str),
        created_at=moment,
    )
    if session is None:
        with session_scope() as own_session:
            own_session.add(row)
    else:
        session.add(row)
    return _record(row)


def list_activity(
    *,
    event_type: str | None = None,
    object_type: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> tuple[tuple[ActivityRecord, ...], str | None]:
    """按创建时间倒序列出活动，返回（本页记录，下一页游标）。"""

    if limit < 1 or limit > MAX_LIMIT:
        raise ValidationError(f"条数上限必须在 1 到 {MAX_LIMIT} 之间: {limit}")
    if start is not None and end is not None and start >= end:
        raise ValidationError("活动时间范围的起点必须早于终点")

    conditions = []
    if event_type is not None:
        conditions.append(ActivityEventRow.event_type == event_type)
    if object_type is not None:
        conditions.append(ActivityEventRow.object_type == object_type)
    if start is not None:
        conditions.append(ActivityEventRow.created_at >= start)
    if end is not None:
        conditions.append(ActivityEventRow.created_at < end)
    if cursor:
        created_at, row_id = _parse_cursor(cursor)
        conditions.append(
            (ActivityEventRow.created_at < created_at)
            | ((ActivityEventRow.created_at == created_at) & (ActivityEventRow.id < row_id))
        )

    statement = (
        select(ActivityEventRow)
        .where(*conditions)
        .order_by(ActivityEventRow.created_at.desc(), ActivityEventRow.id.desc())
        .limit(limit + 1)
    )
    with session_scope() as session:
        rows = list(session.scalars(statement))
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit and page:
        last = page[-1]
        next_cursor = f"{last.created_at.isoformat()}:{last.id}"
    return tuple(_record(row) for row in page), next_cursor


def _record(row: ActivityEventRow) -> ActivityRecord:
    try:
        payload = json.loads(row.payload_json)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"活动 {row.id} 的 payload 不是合法 JSON") from exc
    return ActivityRecord(
        id=row.id,
        event_type=row.event_type,
        object_type=row.object_type,
        object_id=row.object_id,
        summary=row.summary,
        payload=payload if isinstance(payload, dict) else {},
        created_at=row.created_at,
    )


def _parse_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        stamp, row_id = cursor.rsplit(":", maxsplit=1)
        return datetime.fromisoformat(stamp), row_id
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"活动游标不合法: {cursor!r}") from exc

"""研究记录的读写编排与关联校验。

关联标识必须指向真实存在的标的、策略或回测；写入前校验，不存在时按调用方错误
返回 404（由接口层翻译）。创建与更新各写一条活动，活动与记录在同一个事务里。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activity import record_activity
from app.backtest import get_run
from app.core import Clock, NotFound, SystemClock, ValidationError
from app.db import session_scope
from app.instrument import Instrument
from app.research.model import ResearchNoteRow
from app.strategy import get_user_strategy

__all__ = [
    "NOTE_TYPES",
    "ResearchNoteRecord",
    "create_note",
    "delete_note",
    "get_note",
    "list_notes",
    "update_note",
]

NOTE_TYPES = ("hypothesis", "backtest_conclusion", "decision", "review")
SORT_MODES = ("created_at_desc", "created_at_asc")
MAX_LIMIT = 200
_REFERENCE_FIELDS = ("instrument_id", "strategy_id", "backtest_id")


@dataclass(frozen=True, slots=True)
class ResearchNoteRecord:
    """一条研究记录的只读视图；字段名与数据库列一致。"""

    id: str
    type: str
    title: str
    content: str
    instrument_id: str | None
    strategy_id: str | None
    backtest_id: str | None
    tags: tuple[str, ...]
    created_at: datetime
    updated_at: datetime


def create_note(
    *,
    type: str,
    title: str,
    content: str,
    instrument_id: str | None = None,
    strategy_id: str | None = None,
    backtest_id: str | None = None,
    tags: Sequence[str] | None = None,
    clock: Clock | None = None,
) -> ResearchNoteRecord:
    """创建一条研究记录并写活动。"""

    note_type = _require_type(type)
    clean_title = _require_title(title)
    clean_content = _require_content(content)
    clean_tags = _require_tags(tags or ())
    moment = (clock or SystemClock()).now()
    with session_scope() as session:
        _require_links(session, instrument_id, strategy_id, backtest_id)
        row = ResearchNoteRow(
            id="rn_" + uuid4().hex[:24],
            type=note_type,
            title=clean_title,
            content=clean_content,
            instrument_id=_clean_optional(instrument_id),
            strategy_id=_clean_optional(strategy_id),
            backtest_id=_clean_optional(backtest_id),
            tags_json=json.dumps(clean_tags, ensure_ascii=False),
            created_at=moment,
            updated_at=moment,
        )
        session.add(row)
        session.flush()
        record_activity(
            session=session,
            event_type="research_note.created",
            object_type="research_note",
            object_id=row.id,
            summary=f"创建研究记录「{row.title}」",
            payload={"type": row.type, "backtest_id": row.backtest_id},
            clock=clock,
        )
    return _record(row)


def list_notes(
    *,
    type: str | None = None,
    instrument_id: str | None = None,
    strategy_id: str | None = None,
    backtest_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 50,
    cursor: str | None = None,
    sort: str = "created_at_desc",
) -> tuple[tuple[ResearchNoteRecord, ...], str | None]:
    """按类型、关联对象与时间筛选，返回（本页记录，下一页游标）。"""

    if limit < 1 or limit > MAX_LIMIT:
        raise ValidationError(f"条数上限必须在 1 到 {MAX_LIMIT} 之间: {limit}")
    if sort not in SORT_MODES:
        raise ValidationError(f"不支持的排序方式 {sort!r}")
    if start is not None and end is not None and start >= end:
        raise ValidationError("研究记录时间范围的起点必须早于终点")

    conditions = []
    if type is not None:
        conditions.append(ResearchNoteRow.type == _require_type(type))
    if instrument_id is not None:
        conditions.append(ResearchNoteRow.instrument_id == instrument_id.strip())
    if strategy_id is not None:
        conditions.append(ResearchNoteRow.strategy_id == strategy_id.strip())
    if backtest_id is not None:
        conditions.append(ResearchNoteRow.backtest_id == backtest_id.strip())
    if start is not None:
        conditions.append(ResearchNoteRow.created_at >= start)
    if end is not None:
        conditions.append(ResearchNoteRow.created_at < end)

    descending = sort == "created_at_desc"
    if cursor:
        created_at, row_id = _parse_cursor(cursor)
        if descending:
            conditions.append(
                (ResearchNoteRow.created_at < created_at)
                | ((ResearchNoteRow.created_at == created_at) & (ResearchNoteRow.id < row_id))
            )
        else:
            conditions.append(
                (ResearchNoteRow.created_at > created_at)
                | ((ResearchNoteRow.created_at == created_at) & (ResearchNoteRow.id > row_id))
            )

    order = (
        (ResearchNoteRow.created_at.desc(), ResearchNoteRow.id.desc())
        if descending
        else (ResearchNoteRow.created_at.asc(), ResearchNoteRow.id.asc())
    )
    statement = select(ResearchNoteRow).where(*conditions).order_by(*order).limit(limit + 1)
    with session_scope() as session:
        rows = list(session.scalars(statement))
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit and page:
        last = page[-1]
        next_cursor = f"{last.created_at.isoformat()}:{last.id}"
    return tuple(_record(row) for row in page), next_cursor


def get_note(note_id: str) -> ResearchNoteRecord | None:
    with session_scope() as session:
        row = session.get(ResearchNoteRow, note_id)
    return None if row is None else _record(row)


def update_note(
    note_id: str,
    changes: Mapping[str, object],
    *,
    clock: Clock | None = None,
) -> ResearchNoteRecord | None:
    """更新标题、内容、标签或关联对象；至少提交一项。"""

    if not changes:
        raise ValidationError("更新请求至少需要一项字段")
    unknown = sorted(set(changes) - {"type", "title", "content", "tags", *_REFERENCE_FIELDS})
    if unknown:
        raise ValidationError(f"更新请求含未知字段: {', '.join(unknown)}")
    moment = (clock or SystemClock()).now()
    with session_scope() as session:
        row = session.get(ResearchNoteRow, note_id, with_for_update=True)
        if row is None:
            return None
        if "type" in changes:
            row.type = _require_type(changes["type"])
        if "title" in changes:
            row.title = _require_title(changes["title"])
        if "content" in changes:
            row.content = _require_content(changes["content"])
        if "tags" in changes:
            row.tags_json = json.dumps(_require_tags(changes["tags"]), ensure_ascii=False)
        references = {name: changes[name] for name in _REFERENCE_FIELDS if name in changes}
        _require_links(
            session,
            references.get("instrument_id", row.instrument_id),
            references.get("strategy_id", row.strategy_id),
            references.get("backtest_id", row.backtest_id),
        )
        for name in _REFERENCE_FIELDS:
            if name in references:
                setattr(row, name, _clean_optional(references[name]))
        row.updated_at = moment
        record_activity(
            session=session,
            event_type="research_note.updated",
            object_type="research_note",
            object_id=row.id,
            summary=f"更新研究记录「{row.title}」",
            payload={"fields": sorted(changes)},
            clock=clock,
        )
    return get_note(note_id)


def delete_note(note_id: str) -> bool:
    """删除一条研究记录；不存在返回 `False`。"""

    with session_scope() as session:
        row = session.get(ResearchNoteRow, note_id)
        if row is None:
            return False
        session.delete(row)
    return True


def _require_links(
    session: Session,
    instrument_id: str | None,
    strategy_id: str | None,
    backtest_id: str | None,
) -> None:
    instrument = _clean_optional(instrument_id)
    if instrument is not None and session.get(Instrument, instrument) is None:
        raise NotFound(f"未找到标的 {instrument}")
    strategy = _clean_optional(strategy_id)
    if strategy is not None and get_user_strategy(strategy) is None:
        raise NotFound(f"未找到策略 {strategy}")
    backtest = _clean_optional(backtest_id)
    if backtest is not None and get_run(backtest) is None:
        raise NotFound(f"未找到回测 {backtest}")


def _record(row: ResearchNoteRow) -> ResearchNoteRecord:
    try:
        tags = json.loads(row.tags_json)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"研究记录 {row.id} 的标签不是合法 JSON") from exc
    return ResearchNoteRecord(
        id=row.id,
        type=row.type,
        title=row.title,
        content=row.content,
        instrument_id=row.instrument_id,
        strategy_id=row.strategy_id,
        backtest_id=row.backtest_id,
        tags=tuple(str(tag) for tag in tags) if isinstance(tags, list) else (),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _require_type(value: object) -> str:
    if value not in NOTE_TYPES:
        raise ValidationError(f"记录类型必须是 {', '.join(NOTE_TYPES)}")
    return str(value)


def _require_title(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("记录标题不能为空")
    title = value.strip()
    if len(title) > 256:
        raise ValidationError("记录标题不能超过 256 个字符")
    return title


def _require_content(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("记录内容不能为空")
    return value.strip()


def _require_tags(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise ValidationError("记录标签必须是字符串数组")
    tags: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError("记录标签不能为空字符串")
        tags.append(item.strip())
    return tags


def _clean_optional(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("关联标识不能为空")
    return value.strip()


def _parse_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        stamp, row_id = cursor.rsplit(":", maxsplit=1)
        return datetime.fromisoformat(stamp), row_id
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"研究记录游标不合法: {cursor!r}") from exc

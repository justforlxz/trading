"""研究记录端点：CRUD、筛选与关联对象。

端点只做参数映射与响应组装；校验与事务在 `app.research`。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime

from app.api.schemas import (
    ResearchNoteCreatedResponse,
    ResearchNoteCreateRequest,
    ResearchNoteItem,
    ResearchNoteListResponse,
    ResearchNoteUpdatedResponse,
    ResearchNoteUpdateRequest,
)
from app.research import (
    ResearchNoteRecord,
    create_note,
    delete_note,
    get_note,
    list_notes,
    update_note,
)

__all__ = ["research_router"]

research_router = APIRouter(tags=["research"])


@research_router.get("/research-notes", response_model=ResearchNoteListResponse)
def get_research_notes(
    type: str | None = Query(None),
    related_instrument_id: str | None = Query(None),
    related_strategy_id: str | None = Query(None),
    related_backtest_id: str | None = Query(None),
    start: AwareDatetime | None = Query(None, alias="from"),
    end: AwareDatetime | None = Query(None, alias="to"),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    sort: str = Query("created_at_desc"),
) -> ResearchNoteListResponse:
    """按类型、关联标的/策略/回测与时间筛选研究记录。"""

    records, next_cursor = list_notes(
        type=type,
        instrument_id=related_instrument_id,
        strategy_id=related_strategy_id,
        backtest_id=related_backtest_id,
        start=start,
        end=end,
        limit=limit,
        cursor=cursor,
        sort=sort,
    )
    return ResearchNoteListResponse(
        items=[_item(record) for record in records],
        next_cursor=next_cursor,
    )


@research_router.post(
    "/research-notes", response_model=ResearchNoteCreatedResponse, status_code=201
)
def post_research_note(payload: ResearchNoteCreateRequest) -> ResearchNoteCreatedResponse:
    record = create_note(
        type=payload.type,
        title=payload.title,
        content=payload.content,
        instrument_id=payload.related_instrument_id,
        strategy_id=payload.related_strategy_id,
        backtest_id=payload.related_backtest_id,
        tags=payload.tags,
    )
    return ResearchNoteCreatedResponse(
        id=record.id,
        type=record.type,  # type: ignore[arg-type]
        title=record.title,
        created_at=record.created_at,
    )


@research_router.get("/research-notes/{note_id}", response_model=ResearchNoteItem)
def get_research_note(note_id: str) -> ResearchNoteItem:
    record = get_note(note_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到研究记录 {note_id}")
    return _item(record)


@research_router.put("/research-notes/{note_id}", response_model=ResearchNoteUpdatedResponse)
def put_research_note(
    note_id: str, payload: ResearchNoteUpdateRequest
) -> ResearchNoteUpdatedResponse:
    changes = payload.model_dump(exclude_unset=True)
    for api_name, db_name in (
        ("related_instrument_id", "instrument_id"),
        ("related_strategy_id", "strategy_id"),
        ("related_backtest_id", "backtest_id"),
    ):
        if api_name in changes:
            changes[db_name] = changes.pop(api_name)
    record = update_note(note_id, changes)
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到研究记录 {note_id}")
    return ResearchNoteUpdatedResponse(
        id=record.id,
        type=record.type,  # type: ignore[arg-type]
        title=record.title,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@research_router.delete("/research-notes/{note_id}", status_code=204, response_model=None)
def remove_research_note(note_id: str) -> None:
    if not delete_note(note_id):
        raise HTTPException(status_code=404, detail=f"未找到研究记录 {note_id}")


def _item(record: ResearchNoteRecord) -> ResearchNoteItem:
    return ResearchNoteItem(
        id=record.id,
        type=record.type,  # type: ignore[arg-type]
        title=record.title,
        content=record.content,
        related_instrument_id=record.instrument_id,
        related_strategy_id=record.strategy_id,
        related_backtest_id=record.backtest_id,
        tags=list(record.tags),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )

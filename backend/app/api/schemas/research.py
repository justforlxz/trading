"""研究记录契约：创建、更新、列表与详情。

数据库列名是 `instrument_id` / `strategy_id` / `backtest_id`；对外字段带 `related_`
前缀，明确它们是可选的关联引用。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.schemas.common import UtcDatetime

__all__ = [
    "ResearchNoteCreateRequest",
    "ResearchNoteCreatedResponse",
    "ResearchNoteItem",
    "ResearchNoteListResponse",
    "ResearchNoteType",
    "ResearchNoteUpdateRequest",
    "ResearchNoteUpdatedResponse",
]

ResearchNoteType = Literal["hypothesis", "backtest_conclusion", "decision", "review"]

_EXAMPLE_NOTE = {
    "id": "rn_0001",
    "type": "hypothesis",
    "title": "AAPL 突破假设",
    "content": "收盘价站上 MA20 后观察三日",
    "related_instrument_id": "XAAPL-USDT",
    "related_strategy_id": "st_0001",
    "related_backtest_id": "bt_0001",
    "tags": ["趋势", "验证中"],
    "created_at": "2026-11-10T23:00:00Z",
    "updated_at": "2026-11-10T23:00:00Z",
}


class ResearchNoteItem(BaseModel):
    id: str
    type: ResearchNoteType
    title: str
    content: str
    related_instrument_id: str | None = None
    related_strategy_id: str | None = None
    related_backtest_id: str | None = None
    tags: list[str]
    created_at: UtcDatetime
    updated_at: UtcDatetime

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_NOTE]})


class ResearchNoteListResponse(BaseModel):
    items: list[ResearchNoteItem]
    next_cursor: str | None = None

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [_EXAMPLE_NOTE], "next_cursor": None}]}
    )


class ResearchNoteCreateRequest(BaseModel):
    type: ResearchNoteType
    title: str
    content: str
    related_instrument_id: str | None = None
    related_strategy_id: str | None = None
    related_backtest_id: str | None = None
    tags: list[str] = Field(default_factory=list)


_EXAMPLE_CREATED = {
    "id": "rn_0001",
    "type": "hypothesis",
    "title": "AAPL 突破假设",
    "created_at": "2026-11-10T23:00:00Z",
}


class ResearchNoteCreatedResponse(BaseModel):
    id: str
    type: ResearchNoteType
    title: str
    created_at: UtcDatetime

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_CREATED]})


class ResearchNoteUpdateRequest(BaseModel):
    type: ResearchNoteType | None = None
    title: str | None = None
    content: str | None = None
    related_instrument_id: str | None = None
    related_strategy_id: str | None = None
    related_backtest_id: str | None = None
    tags: list[str] | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> ResearchNoteUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("更新请求至少需要一项字段")
        return self


_EXAMPLE_UPDATED = {
    "id": "rn_0001",
    "type": "hypothesis",
    "title": "AAPL 突破假设（更新）",
    "created_at": "2026-11-10T23:00:00Z",
    "updated_at": "2026-11-11T01:00:00Z",
}


class ResearchNoteUpdatedResponse(BaseModel):
    id: str
    type: ResearchNoteType
    title: str
    created_at: UtcDatetime
    updated_at: UtcDatetime

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_UPDATED]})

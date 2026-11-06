"""行情相关请求体与查询参数的校验模型（响应直接由业务层组装，避免二次映射）。"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from app.market.core.bars import CANONICAL_BARS, normalize_bar


class BackfillRequest(BaseModel):
    """`POST /market/backfill` 的请求体。"""

    inst_id: Annotated[str, Field(min_length=1)]
    bar: Annotated[str, Field(min_length=1)]
    start: datetime
    end: datetime

    @field_validator("bar")
    @classmethod
    def _normalize_bar(cls, value: str) -> str:
        try:
            return normalize_bar(value)
        except ValueError as error:
            raise ValueError(str(error)) from error

    @field_validator("start", "end")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware ISO-8601 (e.g. ...Z)")
        return value

    @field_validator("end")
    @classmethod
    def _check_window(cls, value: datetime, info: ValidationInfo) -> datetime:
        start = info.data.get("start")
        if start is not None and value <= start:
            raise ValueError("end must be after start")
        return value


__all__ = ["CANONICAL_BARS", "BackfillRequest"]

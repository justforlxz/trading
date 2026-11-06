"""研究域请求体校验模型（目标股票、关系重算）。

交易所与计算口径都用 `Literal` 收敛：非法取值由 FastAPI 直接给 422，
业务层不需要再写一遍白名单判断。
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

Exchange = Literal["XNAS", "XNYS", "NYSE_ARCA"]
CorrelationMethod = Literal["pearson", "spearman"]
PriceBasis = Literal["okx_close", "equity_close"]


def _require_timezone(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware ISO-8601 (e.g. ...Z)")
    return value


class TargetCreate(BaseModel):
    """`POST /targets` 的请求体。"""

    symbol: Annotated[str, Field(min_length=1, max_length=32)]
    exchange: Exchange
    display_name: Annotated[str | None, Field(default=None, max_length=128)] = None
    note: Annotated[str | None, Field(default=None, max_length=1024)] = None

    @field_validator("symbol")
    @classmethod
    def _normalize_symbol(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("symbol must not be blank")
        return normalized


class TargetUpdate(BaseModel):
    """`PATCH /targets/{id}`：只允许改展示名与备注。"""

    display_name: Annotated[str | None, Field(default=None, max_length=128)] = None
    note: Annotated[str | None, Field(default=None, max_length=1024)] = None


class RecomputeRequest(BaseModel):
    """`POST /targets/{id}/relations/recompute` 的请求体。"""

    window_bars: Annotated[int, Field(ge=3, le=2000)]
    method: CorrelationMethod = "pearson"
    price_basis: PriceBasis = "okx_close"
    as_of: datetime | None = None

    @field_validator("as_of")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_timezone(value)


__all__ = [
    "CorrelationMethod",
    "Exchange",
    "PriceBasis",
    "RecomputeRequest",
    "TargetCreate",
    "TargetUpdate",
]

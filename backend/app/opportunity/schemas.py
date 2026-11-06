"""机会域请求体校验模型（P1-13：全市场扫描）。

阈值参数用 `Field` 收敛到物理上合理的区间：越界由 FastAPI 直接给 422，
扫描器内部不需要再写一遍防御性判断。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

OpportunityKind = Literal["directional", "relative_value"]
OpportunityDirection = Literal["long", "short", "pair"]


def _require_timezone(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware ISO-8601 (e.g. ...Z)")
    return value


class ScanParams(BaseModel):
    """可覆盖的扫描阈值；未提供的项沿用 `Settings` 里的默认值。"""

    model_config = ConfigDict(extra="forbid")

    bar: Literal["1d"] | None = None
    lookback_bars: Annotated[int | None, Field(default=None, ge=21, le=250)] = None
    min_overlap: Annotated[int | None, Field(default=None, ge=5, le=500)] = None
    cluster_threshold: Annotated[float | None, Field(default=None, ge=0.0, le=2.0)] = None
    min_cluster_size: Annotated[int | None, Field(default=None, ge=2, le=50)] = None
    min_correlation: Annotated[float | None, Field(default=None, ge=-1.0, le=1.0)] = None
    spread_z: Annotated[float | None, Field(default=None, ge=0.0, le=10.0)] = None
    resonance_threshold: Annotated[float | None, Field(default=None, ge=0.0, le=1.0)] = None
    anomaly_window: Annotated[int | None, Field(default=None, ge=5, le=120)] = None
    anomaly_min_corr: Annotated[float | None, Field(default=None, ge=0.0, le=1.0)] = None
    anomaly_min_delta: Annotated[float | None, Field(default=None, ge=0.0, le=2.0)] = None
    max_pairs: Annotated[int | None, Field(default=None, ge=1, le=200)] = None

    def overrides(self) -> dict[str, object]:
        """只保留显式提供的键，避免把默认值重复写进参数快照。"""

        return {key: value for key, value in self.model_dump().items() if value is not None}


class ScanRequest(BaseModel):
    """`POST /opportunities/scan` 的请求体；全部字段可选。"""

    as_of: datetime | None = None
    universe: list[str] | None = None
    params: ScanParams | None = None

    @field_validator("as_of")
    @classmethod
    def _check_as_of(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_timezone(value)

    @field_validator("universe")
    @classmethod
    def _check_universe(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item.strip() for item in value if item.strip()]
        return cleaned or None


__all__ = [
    "OpportunityDirection",
    "OpportunityKind",
    "ScanParams",
    "ScanRequest",
]

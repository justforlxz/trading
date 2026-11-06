"""`/strategies` 的请求体；响应在 `api.py` 里按字段逐项组装。"""

from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

Side = Literal["long", "short"]


class StrategyKind(StrEnum):
    directional = "directional"
    relative_value = "relative_value"


class StrategyStatus(StrEnum):
    draft = "draft"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    archived = "archived"


class CreateStrategyRequest(BaseModel):
    """生成策略的唯一入口：同参数复用 `strategy_key`，不重复建记录。

    `params` 承载构建阈值（`min_legs`、`max_position_weight` 等）与来源定位
    （`opportunity_id`）；数据窗口由机会批次的运行参数或关系快照决定，不接受
    请求覆盖。服务端会把解析出的来源与排除原因回写进 `params`，保证策略可复算、
    可审计。
    """

    kind: StrategyKind
    name: str = Field(min_length=1, max_length=200)
    target_id: int | None = None
    templates: list[str] = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class LegInput(BaseModel):
    """草案编辑时用户显式给出的腿；权重符号必须与方向一致。"""

    instrument_id: int
    side: Side
    target_weight: Decimal
    rationale: str = Field(min_length=1)
    rank: int = 0


class PatchStrategyRequest(BaseModel):
    """仅 `draft` / `rejected` 可编辑；任何字段缺省表示保持不变。"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    params: dict[str, Any] | None = None
    legs: list[LegInput] | None = None


class ApproveRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)
    note: str | None = None


class RejectRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1)


__all__ = [
    "ApproveRequest",
    "CreateStrategyRequest",
    "LegInput",
    "PatchStrategyRequest",
    "RejectRequest",
    "Side",
    "StrategyKind",
    "StrategyStatus",
]

"""风险事件的落库模型。

每次拒绝至少留一条记录：哪条规则、哪个实例与标的、触发条件是什么、何时发生。
事件是审计数据，不随策略实例删除；`instance_id` 只是标识，不建外键。分级处置
（T6.5）会在同一张表上追加严重程度与动作列，因此本表不预先声明这些字段。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UtcDateTime

__all__ = ["RiskEventRow"]


class RiskEventRow(Base):
    """一条风控拒绝记录；只增不改，处置状态由 `resolved_at` 表示。"""

    __tablename__ = "risk_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    inst_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    rule: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detail: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

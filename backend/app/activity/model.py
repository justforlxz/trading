"""活动事件表：业务动作发生时追加一条不可编辑的流水。

活动是「谁在什么时刻对哪个对象做了什么」的事实记录，只追加、不修改、不删除。
它不是从其他业务表临时拼出来的视图：首页和记录页读到的就是这里写入的行。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UtcDateTime

__all__ = ["ActivityEventRow"]


class ActivityEventRow(Base):
    """一条活动流水；对象标识按 `object_type` 解释，不建跨表外键。"""

    __tablename__ = "activity_events"
    __table_args__ = (
        Index("ix_activity_events_created_at_id", "created_at", "id"),
        Index("ix_activity_events_event_type", "event_type"),
        Index("ix_activity_events_object", "object_type", "object_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str] = mapped_column(String(512), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

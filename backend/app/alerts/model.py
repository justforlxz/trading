"""提醒事件表：去重后的待处理信号与风险事件。

`dedup_key` 唯一，是「同一标的、同一规则、同一 bar、同一方向或阈值只留一条」的
数据库保证。删除提醒不提供接口：条件恢复时只把状态改成 `expired`，事件本身保留。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UtcDateTime

__all__ = ["AlertEventRow"]


class AlertEventRow(Base):
    """一条提醒事件；`payload_json` 保存触发时的数值与阈值。"""

    __tablename__ = "alert_events"
    __table_args__ = (
        Index("ix_alert_events_status_triggered", "status", "triggered_at"),
        Index("ix_alert_events_type_instrument", "type", "instrument_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    instrument_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("instruments.symbol", ondelete="SET NULL"),
        nullable=True,
    )
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    triggered_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

"""投递通道的协议与投递结果。

一个通道只做一件事：把已经判定过的告警送到用户能看见的地方。它不判断规则、不改
告警内容，也不吞掉失败——失败原样返回，由注册表写一行投递记录，便于排查「为什么
浏览器没弹」。

`notification_deliveries` 是投递台账：每次投递一行，`status` 只有 `delivered` 与
`failed` 两种，`error` 只放失败原因，不放告警正文。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UtcDateTime
from app.events.event import DomainEvent

__all__ = ["DeliveryResult", "DeliveryStatus", "NotificationDeliveryRow", "Sink"]

DeliveryStatus = Literal["delivered", "failed"]


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """一次投递的结果：哪个通道、成没成、失败原因。"""

    channel: str
    status: DeliveryStatus
    error: str | None = None


class Sink(Protocol):
    """投递通道：只声明接收哪类事件，并把它送出去。"""

    name: str

    def accepts(self, event: DomainEvent) -> bool: ...

    async def deliver(self, event: DomainEvent) -> DeliveryResult: ...


class NotificationDeliveryRow(Base):
    """一行投递台账：哪条告警、走哪个通道、成没成、什么时候。"""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        Index("ix_notification_deliveries_alert", "alert_id"),
        Index("ix_notification_deliveries_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    alert_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

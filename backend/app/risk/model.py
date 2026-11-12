"""风险事件的落库模型。

每次拒绝至少留一条记录：哪条规则、哪个实例与标的、触发条件是什么、何时发生。
事件是审计数据，不随策略实例删除；`instance_id` 只是标识，不建外键。

T6.5 分级处置在同一张表上追加四列：

- `severity`：`light` / `medium` / `severe`。
- `action`：本次处置的动作，多个动作用逗号连接。
- `target_product_key`：处置针对的产品键。
- `overridden_approval_id`：被本次处置覆盖的待批准组合申请；没有覆盖时为空。
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
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_product_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    overridden_approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

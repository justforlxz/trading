"""自选域的持久化模型：分组、自选条目、价格提醒。

三张表与 PRD 的日常入口一一对应：`watchlists` 是分组注册表（组的生命周期由
条目决定，空组不保留），`watchlist_items` 是「标的 → 分组」的归属关系，
`price_alerts` 是挂在条目上的提醒规则（同一标的至多一条）。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, DecimalText, UtcDateTime

__all__ = ["PriceAlertRow", "WatchlistGroup", "WatchlistItemRow"]


class WatchlistGroup(Base):
    """自选分组；名字即主键，创建时间决定列表顺序。"""

    __tablename__ = "watchlists"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class WatchlistItemRow(Base):
    """一个自选条目：标的一定来自已同步的标的表，且只属于一个分组。"""

    __tablename__ = "watchlist_items"

    inst_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("instruments.symbol"), primary_key=True
    )
    group_name: Mapped[str] = mapped_column(String(64), ForeignKey("watchlists.name"), index=True)
    added_at: Mapped[datetime] = mapped_column(UtcDateTime)


class PriceAlertRow(Base):
    """价格提醒规则：方向 + 触发价 + 是否启用，触发时间由后续节点回填。"""

    __tablename__ = "price_alerts"

    inst_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("watchlist_items.inst_id"), primary_key=True
    )
    direction: Mapped[str] = mapped_column(String(8))
    price: Mapped[Decimal] = mapped_column(DecimalText)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    triggered_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

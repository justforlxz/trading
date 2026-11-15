"""自选域的持久化模型：分组与自选条目。

两张表与 PRD 的日常入口一一对应：`watchlists` 是分组注册表（组的生命周期由
条目决定，空组不保留），`watchlist_items` 是「标的 → 分组」的归属关系。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UtcDateTime

__all__ = ["WatchlistGroup", "WatchlistItemRow"]


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

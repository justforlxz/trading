"""研究记录表：假设、回测结论、决策与复盘。

内容由用户写，不由 AI 改写。关联的标的、策略和回测是可选引用；被引用对象删除时
把引用置空，记录本身保留，历史研究不跟着消失。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UtcDateTime

__all__ = ["ResearchNoteRow"]


class ResearchNoteRow(Base):
    """一条研究记录；`tags_json` 是字符串数组的 JSON 文本。"""

    __tablename__ = "research_notes"
    __table_args__ = (
        Index("ix_research_notes_type_created", "type", "created_at"),
        Index("ix_research_notes_instrument", "instrument_id"),
        Index("ix_research_notes_strategy", "strategy_id"),
        Index("ix_research_notes_backtest", "backtest_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    instrument_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("instruments.symbol", ondelete="SET NULL"),
        nullable=True,
    )
    strategy_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("strategies.id", ondelete="SET NULL"),
        nullable=True,
    )
    backtest_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("backtest_runs.run_id", ondelete="SET NULL"),
        nullable=True,
    )
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

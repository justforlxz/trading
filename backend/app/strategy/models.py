"""strategy schema 的 ORM 模型（P1：策略头、策略腿、审批与状态迁移审计）。

字段与唯一键对应 `docs/architecture/data-model.md` §5。策略腿只引用白名单内的
`market.instrument.id`，`target_id` 只引用 `research.target_symbol.id`；除这两条外
不与其他业务 schema 建外键，生成所需的源数据由 `sources.py` 只读查询。
"""

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SCHEMA = "strategy"
WEIGHT = Numeric(12, 10)


class Strategy(Base):
    """一条策略头；`strategy_key` 唯一，即同参数重复生成的幂等闸门。"""

    __tablename__ = "strategy"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("strategy_key", name="uq_strategy_key"),
        UniqueConstraint("id", "version", name="uq_strategy_version"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    strategy_key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    target_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("research.target_symbol.id", ondelete="SET NULL")
    )
    templates: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 运行暂停标记（MCP `pause_strategy` / `resume_strategy` 写入）；`status` 仍是
    # 五值状态机，暂停只影响「是否允许新的执行动作」，不改变策略状态。
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StrategyLeg(Base):
    """策略腿；同一策略内同一标的不允许重复（唯一键兜底）。"""

    __tablename__ = "strategy_leg"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("strategy_id", "instrument_id", name="uq_strategy_leg_member"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SCHEMA}.strategy.id", ondelete="CASCADE"),
        nullable=False,
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instrument.id", ondelete="CASCADE"), nullable=False
    )
    side: Mapped[str] = mapped_column(Text, nullable=False)
    target_weight: Mapped[Any] = mapped_column(WEIGHT, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class StrategyApproval(Base):
    """审批记录；`(strategy_id, content_hash, decision)` 唯一，内容变了必须重审。"""

    __tablename__ = "strategy_approval"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint(
            "strategy_id", "content_hash", "decision", name="uq_strategy_approval_key"
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SCHEMA}.strategy.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StrategyTransition(Base):
    """状态迁移审计链；只追加，不更新，按 `(strategy_id, at)` 建索引。"""

    __tablename__ = "strategy_transition"
    __table_args__: ClassVar[Any] = (
        Index("ix_strategy_transition_at", "strategy_id", "at"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SCHEMA}.strategy.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_status: Mapped[str] = mapped_column(Text, nullable=False)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)


__all__ = [
    "SCHEMA",
    "Strategy",
    "StrategyApproval",
    "StrategyLeg",
    "StrategyTransition",
]

"""risk schema 的 ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
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

SCHEMA = "risk"
MONEY = Numeric(24, 10)
RATIO = Numeric(12, 10)


class RiskPolicy(Base):
    """风控阈值策略，按 (scope, strategy_id) 维护单调递增的版本。"""

    __tablename__ = "risk_policy"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint(
            "scope",
            "strategy_id",
            "version",
            name="uq_risk_policy_version",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "(scope = 'global' AND strategy_id IS NULL)"
            " OR (scope = 'strategy' AND strategy_id IS NOT NULL)",
            name="ck_risk_policy_scope",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("strategy.strategy.id", ondelete="CASCADE"),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    max_order_notional: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    max_leg_weight: Mapped[Decimal] = mapped_column(RATIO, nullable=False)
    max_leverage: Mapped[Decimal] = mapped_column(RATIO, nullable=False)
    max_gross_exposure: Mapped[Decimal] = mapped_column(RATIO, nullable=False)
    max_net_exposure: Mapped[Decimal] = mapped_column(RATIO, nullable=False)
    max_instrument_weight: Mapped[Decimal] = mapped_column(RATIO, nullable=False)
    max_concentration: Mapped[Decimal] = mapped_column(RATIO, nullable=False)
    drawdown_warn: Mapped[Decimal] = mapped_column(RATIO, nullable=False)
    drawdown_reduce: Mapped[Decimal] = mapped_column(RATIO, nullable=False)
    drawdown_close: Mapped[Decimal] = mapped_column(RATIO, nullable=False)
    funding_rate_threshold: Mapped[Decimal] = mapped_column(RATIO, nullable=False)
    min_depth_notional: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RiskEvent(Base):
    """风控事件，按五元组幂等。"""

    __tablename__ = "risk_event"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint(
            "kind",
            "strategy_id",
            "instrument_id",
            "policy_version",
            "evaluation_key",
            name="uq_risk_event_key",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_risk_event_created_at", "created_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("strategy.strategy.id", ondelete="SET NULL"),
        nullable=True,
    )
    instrument_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("market.instrument.id", ondelete="SET NULL"),
        nullable=True,
    )
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_value: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    threshold: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="'{}'::jsonb"
    )
    evaluation_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ["MONEY", "RATIO", "SCHEMA", "RiskEvent", "RiskPolicy"]

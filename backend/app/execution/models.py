"""execution schema 的 ORM 模型（P3：订单、成交、策略级虚拟持仓、对账差异）。

字段与唯一键对应 `docs/architecture/data-model.md` §9。跨 schema 外键只引用
白名单内的 `strategy.strategy.id` 与 `market.instrument.id`。
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SCHEMA = "execution"
MONEY = Numeric(24, 10)

ORDER_STATES = ("pending", "submitted", "partial", "filled", "canceled", "rejected")
ORDER_MODES = ("paper", "real")


class Order(Base):
    """一笔订单；`client_order_id` 唯一，是幂等下单的唯一闸门。"""

    __tablename__ = "order"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("client_order_id", name="uq_execution_order_client_id"),
        CheckConstraint(
            "state IN ('pending','submitted','partial','filled','canceled','rejected')",
            name="ck_execution_order_state",
        ),
        CheckConstraint("mode IN ('paper','real')", name="ck_execution_order_mode"),
        CheckConstraint("side IN ('buy','sell')", name="ck_execution_order_side"),
        CheckConstraint(
            "position_side IN ('long','short')", name="ck_execution_order_position_side"
        ),
        CheckConstraint("order_type IN ('market','limit')", name="ck_execution_order_type"),
        CheckConstraint("intent IN ('entry','exit','stop')", name="ck_execution_order_intent"),
        CheckConstraint("quantity > 0", name="ck_execution_order_quantity"),
        CheckConstraint(
            "filled_quantity >= 0 AND filled_quantity <= quantity",
            name="ck_execution_order_filled",
        ),
        Index("ix_execution_order_state", "state"),
        Index("ix_execution_order_strategy", "strategy_id", "created_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_order_id: Mapped[str] = mapped_column(Text, nullable=False)
    exchange_order_id: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(Text, nullable=False, default="paper")
    strategy_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("strategy.strategy.id", ondelete="SET NULL")
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instrument.id", ondelete="CASCADE"), nullable=False
    )
    inst_id: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    position_side: Mapped[str] = mapped_column(Text, nullable=False)
    order_type: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    price: Mapped[Decimal | None] = mapped_column(MONEY)
    reduce_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    intent: Mapped[str] = mapped_column(Text, nullable=False, default="entry")
    state: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    filled_quantity: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    average_price: Mapped[Decimal | None] = mapped_column(MONEY)
    fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    risk_event_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("risk.risk_event.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=UTC),
        onupdate=lambda: datetime.now(tz=UTC),
        server_default=func.now(),
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Fill(Base):
    """一笔成交；`(order_id, fill_id)` 唯一保证重复轮询不会重复记账。"""

    __tablename__ = "fill"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("order_id", "fill_id", name="uq_execution_fill_key"),
        Index("ix_execution_fill_filled_at", "filled_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{SCHEMA}.order.id", ondelete="CASCADE"), nullable=False
    )
    fill_id: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("strategy.strategy.id", ondelete="SET NULL")
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instrument.id", ondelete="CASCADE"), nullable=False
    )
    inst_id: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    position_side: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Position(Base):
    """策略级虚拟持仓；唯一键 `(strategy, instrument, position_side)`。"""

    __tablename__ = "position"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint(
            "strategy_id",
            "instrument_id",
            "position_side",
            name="uq_execution_position_key",
        ),
        CheckConstraint("position_side IN ('long','short')", name="ck_execution_position_side"),
        CheckConstraint("quantity >= 0", name="ck_execution_position_quantity"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("strategy.strategy.id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instrument.id", ondelete="CASCADE"), nullable=False
    )
    inst_id: Mapped[str] = mapped_column(Text, nullable=False)
    position_side: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    average_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=UTC),
        onupdate=lambda: datetime.now(tz=UTC),
        server_default=func.now(),
    )


class ReconcileDiff(Base):
    """本地与交易所不一致的记录；只新增/标记已处理，绝不静默改数。"""

    __tablename__ = "reconcile_diff"
    __table_args__: ClassVar[Any] = (
        Index(
            "uq_execution_reconcile_open",
            "kind",
            "inst_id",
            "position_side",
            "reference",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_execution_reconcile_status", "status", "detected_at"),
        CheckConstraint("status IN ('open','resolved')", name="ck_execution_reconcile_status"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("strategy.strategy.id", ondelete="SET NULL")
    )
    instrument_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("market.instrument.id", ondelete="SET NULL")
    )
    inst_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    position_side: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reference: Mapped[str] = mapped_column(Text, nullable=False, default="")
    local_value: Mapped[Decimal | None] = mapped_column(MONEY)
    exchange_value: Mapped[Decimal | None] = mapped_column(MONEY)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=UTC),
        server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    resolve_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


__all__ = [
    "ORDER_MODES",
    "ORDER_STATES",
    "SCHEMA",
    "Fill",
    "Order",
    "Position",
    "ReconcileDiff",
]

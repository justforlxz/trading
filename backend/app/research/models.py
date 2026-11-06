"""research schema 的 ORM 模型（S4：目标股票、关系快照、相对强弱）。

字段与 `docs/architecture/data-model.md` §3 对应。跨 schema 外键只指向白名单内的
`market.instrument.id`，不 JOIN 其他业务表。
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SCHEMA = "research"
RATIO = Numeric(12, 10)
PRICE = Numeric(20, 10)


class TargetSymbol(Base):
    """目标股票：用户显式添加的分析锚点（不意味着必然进入交易组合）。"""

    __tablename__ = "target_symbol"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("symbol", "exchange", name="uq_target_symbol_key"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    instrument_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("market.instrument.id", ondelete="SET NULL")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RelationSnapshot(Base):
    """一次关系计算的结果头；`run_key` 唯一约束即幂等闸门。"""

    __tablename__ = "relation_snapshot"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("run_key", name="uq_relation_snapshot_run_key"),
        UniqueConstraint(
            "target_id",
            "as_of",
            "window_bars",
            "method",
            "price_basis",
            name="uq_relation_snapshot_business",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    target_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{SCHEMA}.target_symbol.id", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_bars: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    price_basis: Mapped[str] = mapped_column(Text, nullable=False)
    lag_max: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    run_key: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class RelationEdge(Base):
    """目标与单个对手方在某个 lag 上的相关关系。"""

    __tablename__ = "relation_edge"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("snapshot_id", "counterparty_id", "best_lag", name="uq_relation_edge_key"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{SCHEMA}.relation_snapshot.id", ondelete="CASCADE"), nullable=False
    )
    counterparty_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instrument.id", ondelete="CASCADE"), nullable=False
    )
    coefficient: Mapped[Decimal] = mapped_column(RATIO, nullable=False)
    best_lag: Mapped[int] = mapped_column(Integer, nullable=False)
    p_value: Mapped[Decimal | None] = mapped_column(RATIO)
    stability: Mapped[Decimal | None] = mapped_column(RATIO)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)


class RelativeStrengthSnapshot(Base):
    """相对强弱快照：按 `run_key` 幂等，供前端画曲线与后续回溯。"""

    __tablename__ = "relative_strength_snapshot"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("run_key", name="uq_relative_strength_snapshot_run_key"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    target_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{SCHEMA}.target_symbol.id", ondelete="CASCADE"), nullable=False
    )
    counterparty_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instrument.id", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lookback_bars: Mapped[int] = mapped_column(Integer, nullable=False)
    rs_ratio: Mapped[Decimal] = mapped_column(RATIO, nullable=False)
    rs_momentum: Mapped[Decimal] = mapped_column(RATIO, nullable=False)
    run_key: Mapped[str] = mapped_column(Text, nullable=False)


class MarketSnapshot(Base):
    """全市场特征截面（P1-11）：每个 `as_of` 每只标的至多一行。

    `run_id` 只用于溯源（哪个扫描批次产生），**不参与唯一键**：同一截面时刻
    重跑只更新自身，不会因为批次不同而出现重复截面。
    """

    __tablename__ = "market_snapshot"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("as_of", "instrument_id", name="uq_market_snapshot_key"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run_id: Mapped[int | None] = mapped_column(BigInteger)
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instrument.id", ondelete="CASCADE"), nullable=False
    )
    ret_1d: Mapped[Decimal | None] = mapped_column(RATIO)
    ret_5d: Mapped[Decimal | None] = mapped_column(RATIO)
    ret_20d: Mapped[Decimal | None] = mapped_column(RATIO)
    vol_20d: Mapped[Decimal | None] = mapped_column(RATIO)
    atr_14: Mapped[Decimal | None] = mapped_column(PRICE)
    volume_z: Mapped[Decimal | None] = mapped_column(RATIO)
    high_20d: Mapped[Decimal | None] = mapped_column(PRICE)
    low_20d: Mapped[Decimal | None] = mapped_column(PRICE)
    extras: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


__all__ = [
    "SCHEMA",
    "MarketSnapshot",
    "RelationEdge",
    "RelationSnapshot",
    "RelativeStrengthSnapshot",
    "TargetSymbol",
]

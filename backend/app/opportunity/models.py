"""opportunity schema 的 ORM 模型（P1：扫描批次、机会、资产簇与成员）。

字段与唯一键对应 `docs/architecture/data-model.md` §4。跨 schema 外键只指向
白名单内的 `market.instrument.id`；机会本体不 JOIN 其他业务表，证据以 JSONB 自洽。
"""

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
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

SCHEMA = "opportunity"
RATIO = Numeric(12, 10)
SCORE = Numeric(12, 10)


class OpportunityRun(Base):
    """一次全市场扫描的批次头；`run_key` 唯一约束即幂等闸门。"""

    __tablename__ = "opportunity_run"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("run_key", name="uq_opportunity_run_key"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_key: Mapped[str] = mapped_column(Text, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    universe_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AssetCluster(Base):
    """某个批次里的一簇标的；`(run_id, label)` 唯一。"""

    __tablename__ = "asset_cluster"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("run_id", "label", name="uq_asset_cluster_label"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SCHEMA}.opportunity_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False, default="hierarchical")
    silhouette: Mapped[Any | None] = mapped_column(RATIO)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    centroid: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClusterMember(Base):
    """簇成员；同一标的在同一簇内只出现一次。"""

    __tablename__ = "cluster_member"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("cluster_id", "instrument_id", name="uq_cluster_member_key"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cluster_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SCHEMA}.asset_cluster.id", ondelete="CASCADE"),
        nullable=False,
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instrument.id", ondelete="CASCADE"), nullable=False
    )
    distance: Mapped[Any] = mapped_column(RATIO, nullable=False, default=0)
    weight: Mapped[Any] = mapped_column(RATIO, nullable=False, default=0)


class Opportunity(Base):
    """一条候选机会；`(run_id, dedupe_key)` 唯一，避免重跑产生副本。"""

    __tablename__ = "opportunity"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("run_id", "dedupe_key", name="uq_opportunity_dedupe"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SCHEMA}.opportunity_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    primary_instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instrument.id", ondelete="CASCADE"), nullable=False
    )
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[Any] = mapped_column(SCORE, nullable=False)
    horizon: Mapped[str] = mapped_column(Text, nullable=False)
    reasons: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "SCHEMA",
    "AssetCluster",
    "ClusterMember",
    "Opportunity",
    "OpportunityRun",
]

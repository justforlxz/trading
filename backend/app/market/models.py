"""market schema 的 ORM 模型（S3：标的、K 线、真实行情、交易日历、数据质量）。

字段与 `docs/architecture/data-model.md` 对应；与文档的已知偏差（不建分区、
新增 basis_snapshot）记录在该文档与 `docs/market-data.md`。
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SCHEMA = "market"

PRICE = Numeric(20, 10)
QTY = Numeric(24, 10)
RATIO = Numeric(12, 10)
# 基差以基点计（1622 bps 这类量级），保留 4 位小数足够且不溢出。
BASIS = Numeric(12, 4)


class Instrument(Base):
    """OKX SWAP 标的（含美股正股 / ETF / 私营公司等全部 543 条）。"""

    __tablename__ = "instrument"
    __table_args__: ClassVar[Any] = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    inst_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    inst_family: Mapped[str] = mapped_column(Text, nullable=False)
    uly: Mapped[str] = mapped_column(Text, nullable=False, default="")
    inst_category: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    asset_class: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str | None] = mapped_column(Text, nullable=True)
    ct_val: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    ct_val_ccy: Mapped[str] = mapped_column(Text, nullable=False)
    lot_sz: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    min_sz: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    tick_sz: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    lever: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    rule_type: Mapped[str] = mapped_column(Text, nullable=False)
    list_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class EquityAsset(Base):
    """真实美股标的（与 OKX 合约解耦：一个 symbol 可能对应多条上市记录）。"""

    __tablename__ = "equity_asset"
    __table_args__: ClassVar[Any] = (
        # PostgreSQL 15+ 才支持 NULLS NOT DISTINCT，避免 exchange 为 NULL 时重复行。
        UniqueConstraint(
            "symbol",
            "exchange",
            name="uq_equity_asset_symbol_exchange",
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="USD")
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="America/New_York")
    source_symbol: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    mapping_status: Mapped[str] = mapped_column(Text, nullable=False, default="unmapped")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Candle(Base):
    """OKX 永续合约 K 线（24/7 成交，与美股交易时段无关）。"""

    __tablename__ = "candle"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("instrument_id", "bar", "open_time", name="uq_candle_key"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{SCHEMA}.instrument.id", ondelete="CASCADE"), nullable=False
    )
    bar: Mapped[str] = mapped_column(Text, nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    high: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    low: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    close: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    vol: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    vol_ccy: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    vol_ccy_quote: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    confirm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EquityCandle(Base):
    """真实美股 K 线（日线为主，分钟线用于时段交叉校验）。"""

    __tablename__ = "equity_candle"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("equity_asset_id", "interval", "ts", name="uq_equity_candle_key"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    equity_asset_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{SCHEMA}.equity_asset.id", ondelete="CASCADE"), nullable=False
    )
    interval: Mapped[str] = mapped_column(Text, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    high: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    low: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    close: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    volume: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    session: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MarketSession(Base):
    """交易日历（P1 只 XNYS），非交易日也保留一行（is_session=False）。"""

    __tablename__ = "market_session"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("venue", "trading_date", name="uq_market_session_key"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    venue: Mapped[str] = mapped_column(Text, nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_session: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_half_day: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_holiday: Mapped[bool] = mapped_column(Boolean, nullable=False)
    pre_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pre_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    regular_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    regular_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    post_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    post_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calendar_source: Mapped[str] = mapped_column(Text, nullable=False)
    calendar_version: Mapped[str] = mapped_column(Text, nullable=False)


class DataSourceSync(Base):
    """每个「源 × 数据集 × 窗口」的采集状态（partial/failed 的原因留在这里）。"""

    __tablename__ = "data_source_sync"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint(
            "source", "dataset", "scope", "window_start", "window_end", name="uq_data_source_sync"
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    dataset: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    coverage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DataQualityIssue(Base):
    """数据质量问题；按 (dataset, scope_id, kind, window_start) 去重只更新 last_seen_at。"""

    __tablename__ = "data_quality_issue"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint(
            "dataset", "scope_id", "kind", "window_start", name="uq_data_quality_issue"
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dataset: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False, default="warning")
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BasisSnapshot(Base):
    """OKX 合约价 vs 真实股价的基差快照（`docs/risk/external-dependencies.md` §2.9）。"""

    __tablename__ = "basis_snapshot"
    __table_args__: ClassVar[Any] = (
        UniqueConstraint("instrument_id", "ts", name="uq_basis_snapshot_key"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{SCHEMA}.instrument.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    okx_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    equity_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    basis_bps: Mapped[Decimal] = mapped_column(BASIS, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

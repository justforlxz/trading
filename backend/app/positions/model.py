"""持仓域的表：OKX 只读快照、手动持仓与不可覆盖的手动流水。

账户与交易所持仓是**快照**：每次同步追加一条，同一 `captured_at` 重复写入由唯一
约束挡住。手动持仓是本地账本：当前数量与成本在事务内更新，`manual_trades` 只追加，
不提供修改和删除接口。

`position_risk_config` 按持仓引用保存用户设置的止损与预警阈值。OKX 持仓没有
现成的用户止损字段，本地配置不能从持仓快照反推，因此单独成表。B3 的风险计算
会读取它，本节点只建表。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, DecimalText, UtcDateTime

__all__ = [
    "AccountSnapshotRow",
    "ExchangePositionSnapshotRow",
    "ManualPositionRow",
    "ManualTradeRow",
    "PositionRiskConfigRow",
]

DEFAULT_ACCOUNT_ID = "okx-main"
DEFAULT_CURRENCY = "USDT"


class AccountSnapshotRow(Base):
    """账户权益快照；同一账户、时刻与来源只保留一行。"""

    __tablename__ = "account_snapshots"
    __table_args__ = (UniqueConstraint("account_id", "captured_at", "source"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    equity: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    available_equity: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    cash_balance: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    used_margin: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    available_margin: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    margin_ratio: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_payload_ref: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExchangePositionSnapshotRow(Base):
    """交易所持仓快照；`(account_id, pos_id, captured_at)` 唯一。"""

    __tablename__ = "exchange_position_snapshots"
    __table_args__ = (
        UniqueConstraint("account_id", "pos_id", "captured_at"),
        Index("ix_exchange_position_snapshots_account_captured", "account_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(32), nullable=False)
    pos_id: Mapped[str] = mapped_column(String(96), nullable=False)
    inst_id: Mapped[str] = mapped_column(String(64), nullable=False)
    pos_side: Mapped[str] = mapped_column(String(8), nullable=False)
    size: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    avg_px: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    mark_px: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    upl: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    upl_ratio: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    lever: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    mgn_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    liq_px: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    margin: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)


class ManualPositionRow(Base):
    """本地记账的一条手动持仓；数量与成本只能通过流水改变。"""

    __tablename__ = "manual_positions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    inst_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    avg_cost: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    stop_px: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    leverage: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class ManualTradeRow(Base):
    """手动持仓的一条流水；只追加，不提供修改与删除接口。"""

    __tablename__ = "manual_trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    position_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("manual_positions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    price: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    fee: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class PositionRiskConfigRow(Base):
    """本地保存的持仓止损与预警阈值；`position_ref` 唯一。"""

    __tablename__ = "position_risk_config"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    position_ref: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    stop_px: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    risk_budget: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    warning_threshold_pct: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

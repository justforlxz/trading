"""组合管理的四张表：策略级虚拟持仓、虚拟成交、资金分配与调整申请。

**两层持仓不混用。** 账户实际持仓归 `app/execution`（T5.2）；这里只记每个策略实例
自己的账：数量、FIFO 成本、已实现盈亏与费用。两者不互相读取，也不互相改写。

`virtual_positions` 一行是一个实例在一个交易所标识上的账本状态。数量归零后**这一行
仍然保留**：已实现盈亏是历史事实，不随平仓消失；`direction` 为空表示当前没有持仓，
`open_positions` 只数真正还有数量的行。

`allocations` 一行是一个实例的资金分配：资金预算、策略优先级，以及**已批准并生效**的
目标组合（`target_json`）。目标组合不另建一张表，是因为「预算、优先级、生效目标」是
同一个分配决定的三部分，分开存会出现三份状态各自过期的情况。申请未批准时目标只存在
`portfolio_adjustments` 里，不写进 `allocations`。

`portfolio_adjustments` 记申请与决定。`note` 是申请人写的说明，`decision_note` 是
决定人写的说明；接口只暴露一个 `note`，取决定说明，没有决定说明时取申请说明。

时间用 `UtcDateTime`（带时区，读回补 UTC），身份与金额用文本列，与仓库其余表同口径。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Identity, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, DecimalText, UtcDateTime

__all__ = [
    "AllocationRow",
    "PortfolioAdjustmentRow",
    "VirtualFillRow",
    "VirtualPositionRow",
]


class VirtualPositionRow(Base):
    """策略账本里一个（实例，标的）的当前状态；平仓后保留一行以留住已实现盈亏。"""

    __tablename__ = "virtual_positions"

    instance_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("strategy_instances.instance_id", ondelete="CASCADE"),
        primary_key=True,
    )
    inst_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    inst_type: Mapped[str] = mapped_column(String(16), nullable=False)
    product_key: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # 空方向 = 已平仓。数据库层面允许为空，是因为「没有持仓」是一个真实状态，
    # 不与「多头 0 张」混成同一种写法。
    direction: Mapped[str | None] = mapped_column(String(8), nullable=True)
    qty: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    avg_cost: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    # 最近一次成交价：本节点没有行情推送，未实现盈亏按它计算，口径写在 service 文档里。
    mark_price: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    realized_pnl: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    fees: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class VirtualFillRow(Base):
    """策略账本里的一笔虚拟成交；只增不改，随实例删除。

    `seq` 是数据库发放的写入顺序。`at` 只有秒精度，同一秒内的多笔成交光看时间无法
    分出先后，而 FIFO 重放必须按真实写入顺序，排序因此落在 `seq` 上。
    """

    __tablename__ = "virtual_fills"

    fill_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    instance_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("strategy_instances.instance_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    inst_id: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    qty: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    price: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    fee: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class AllocationRow(Base):
    """一个策略实例的资金分配与已生效目标组合。"""

    __tablename__ = "allocations"

    instance_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("strategy_instances.instance_id", ondelete="CASCADE"),
        primary_key=True,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    capital_budget: Mapped[Decimal] = mapped_column(DecimalText, nullable=False, default=0)
    target_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class PortfolioAdjustmentRow(Base):
    """一条组合调整申请；批准之前不影响生效目标。"""

    __tablename__ = "portfolio_adjustments"

    adjustment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    instance_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("strategy_instances.instance_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    target_json: Mapped[str] = mapped_column(Text, nullable=False)

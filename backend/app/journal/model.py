"""交易历史（journal）的只读值对象。

本模块只放**读模型**，不碰数据库、网络与时钟。journal 把三类事实并排放在一起：

- 策略实例的配置与版本（来自 `strategy_instances`）；
- 回测预期（来自 `backtest_runs` 的指标）；
- 模拟或实盘的实际成交（来自执行域的订单、成交与持仓）。

两类收益必须各自带来源：预期值来自某一次回测运行，实际值来自某一批成交。两者
不是同一个字段的两种写法，也不允许互相回退填充。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType

from app.core import Fill, ValidationError
from app.execution import AccountPosition, Order

__all__ = [
    "JOURNAL_CATEGORIES",
    "CashFlowPoint",
    "ExecutionSnapshot",
    "JournalEntry",
    "JournalView",
    "RecordedSignal",
    "ReturnPoint",
    "StrategyJournal",
]

#: 交易日志条目允许出现的类别。与 API 契约的 `JournalCategory` 同值。
JOURNAL_CATEGORIES: frozenset[str] = frozenset(
    {"signal", "order", "fill", "mode_change", "risk_block", "settings", "confirmation"}
)

SIDES = frozenset({"long", "short"})


@dataclass(frozen=True, slots=True)
class RecordedSignal:
    """一条已经产生、可追溯到策略实例的信号。

    `app.core.Signal` 只带标的、方向、强度与时刻，没有策略实例与价格；journal 需要
    把信号挂在具体策略上，因此在读模型里补上这两个来源字段。
    """

    signal_id: str
    instance_id: str
    inst_id: str
    inst_type: str
    side: str
    strength: float
    price: Decimal | None
    reason: str
    generated_at: datetime
    target_weight: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("signal_id", "instance_id", "inst_id", "inst_type"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f"信号的 {name} 不能为空")
        if self.side not in SIDES:
            raise ValidationError(f"信号方向必须是 {sorted(SIDES)}, 实际 {self.side!r}")
        if not 0.0 <= float(self.strength) <= 1.0:
            raise ValidationError(f"信号强度必须在 0..1 之间, 实际 {self.strength}")
        if self.price is not None and self.price <= 0:
            raise ValidationError(f"信号价格必须为正, 实际 {self.price}")
        if self.generated_at.tzinfo is None:
            raise ValidationError("信号的 generated_at 必须带时区")


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """交易日志的一条记录。条目由已有事实派生，journal 自己不保存它们。"""

    entry_id: str
    category: str
    message: str
    created_at: datetime
    inst_id: str | None = None

    def __post_init__(self) -> None:
        if not self.entry_id.strip():
            raise ValidationError("交易日志条目必须给出 entry_id")
        if self.category not in JOURNAL_CATEGORIES:
            raise ValidationError(f"未知的交易日志类别 {self.category!r}")
        if not self.message.strip():
            raise ValidationError("交易日志条目的说明不能为空")
        if self.created_at.tzinfo is None:
            raise ValidationError("交易日志条目的 created_at 必须带时区")


@dataclass(frozen=True, slots=True)
class CashFlowPoint:
    """一笔成交引起的资金变化：买入为负（付出），卖出为正（收回），手续费计入。"""

    at: datetime
    inst_id: str
    amount: Decimal

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValidationError("资金变化的时间必须带时区")
        if not self.inst_id.strip():
            raise ValidationError("资金变化必须给出标的")


@dataclass(frozen=True, slots=True)
class ReturnPoint:
    """平掉一笔持仓之后的累计实际收益（已实现盈亏 ÷ 已投入成本）。"""

    at: datetime
    value: Decimal

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValidationError("收益曲线的时间必须带时区")


@dataclass(frozen=True, slots=True)
class ExecutionSnapshot:
    """执行域在某一时刻的事实快照，由调用方注入。

    `order_owners` 把幂等键映射到策略实例：执行域的订单与成交本身不带策略标识，
    没有这份归属信息就无法按策略核算实际成交收益。缺失归属的成交仍会出现在全局
    成交列表里，但不计入任何策略的实际收益。
    """

    mode: str = "manual"
    orders: tuple[Order, ...] = ()
    fills: tuple[Fill, ...] = ()
    positions: tuple[AccountPosition, ...] = ()
    signals: tuple[RecordedSignal, ...] = ()
    order_owners: Mapping[str, str] = field(default_factory=dict)
    entries: tuple[JournalEntry, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "orders", tuple(self.orders))
        object.__setattr__(self, "fills", tuple(self.fills))
        object.__setattr__(self, "positions", tuple(self.positions))
        object.__setattr__(self, "signals", tuple(self.signals))
        object.__setattr__(self, "entries", tuple(self.entries))
        owners = {str(key): str(value) for key, value in self.order_owners.items()}
        object.__setattr__(self, "order_owners", MappingProxyType(owners))


@dataclass(frozen=True, slots=True)
class StrategyJournal:
    """一个策略实例的只读汇总：配置、回测预期与实际成交。"""

    instance_id: str
    strategy_id: str
    strategy_version: str
    name: str
    bar: str
    lifecycle_status: str
    execution_mode: str
    params: Mapping[str, object]
    inst_ids: tuple[str, ...]
    expected_return: Decimal | None
    expected_source: str
    actual_return: Decimal
    actual_source: str
    net_cash_flow: Decimal
    fill_count: int
    cash_flow: tuple[CashFlowPoint, ...] = ()
    actual_curve: tuple[ReturnPoint, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))
        object.__setattr__(self, "inst_ids", tuple(self.inst_ids))
        object.__setattr__(self, "cash_flow", tuple(self.cash_flow))
        object.__setattr__(self, "actual_curve", tuple(self.actual_curve))
        if not self.expected_source.strip():
            raise ValidationError("回测预期收益必须带来源")
        if not self.actual_source.strip():
            raise ValidationError("实际成交收益必须带来源")


@dataclass(frozen=True, slots=True)
class JournalView:
    """Trades 页一次读取所需的全部只读事实。"""

    mode: str
    strategies: tuple[StrategyJournal, ...]
    positions: tuple[AccountPosition, ...]
    orders: tuple[Order, ...]
    fills: tuple[Fill, ...]
    signals: tuple[RecordedSignal, ...]
    entries: tuple[JournalEntry, ...]
    order_owners: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("strategies", "positions", "orders", "fills", "signals", "entries"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        owners = {str(key): str(value) for key, value in self.order_owners.items()}
        object.__setattr__(self, "order_owners", MappingProxyType(owners))

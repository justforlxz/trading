"""只读聚合：把策略实例、回测预期与执行快照合成 Trades 页需要的一份视图。

本模块是纯函数：输入是已经读出的记录与快照，输出是值对象；不打开数据库连接，
不重新计算回测，也不改写执行状态。

## 两个收益各算各的

- **回测预期收益**：直接取某一次回测运行已经算好的 `total_return`，来源写成
  `backtest:<run_id>:metrics.total_return`。
- **实际成交收益**：从模拟或实盘成交按先进先出配对，已实现盈亏除以已投入成本，
  来源写成 `execution:fills:<成交笔数>`。

两者在数据上没有任何回退关系：没有回测就是 `None`，没有成交就是 0，不允许拿
其中一个填另一个。

## 实际收益只算平掉的部分

没有平掉的持仓只在持仓区展示，不进入实际收益：成交价与持仓成本之间的差额在平仓
之前都不是已实现事实。FIFO 配对让「卖出一部分」也能得到可复算的已实现盈亏。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext

from app.core import Fill
from app.execution import Order
from app.journal.model import (
    CashFlowPoint,
    ExecutionSnapshot,
    JournalEntry,
    JournalView,
    ReturnPoint,
    StrategyJournal,
)
from app.strategy import InstanceRecord

__all__ = [
    "RealizedSummary",
    "build_journal",
    "build_strategy_journal",
    "realized_summary",
]

ZERO = Decimal(0)
#: 契约里的 `DecimalString` 最多允许 12 位小数，聚合值在这里一次收敛到位。
_QUANTUM = Decimal("1e-12")


@dataclass(frozen=True, slots=True)
class RealizedSummary:
    """一批成交的已实现结果：盈亏、成本、资金变化与累计收益曲线。"""

    realized_pnl: Decimal
    cost_basis: Decimal
    net_cash_flow: Decimal
    fill_count: int
    cash_flow: tuple[CashFlowPoint, ...]
    curve: tuple[ReturnPoint, ...]

    @property
    def realized_return(self) -> Decimal:
        """已实现盈亏 ÷ 已投入成本；没有平仓过的成交按 0 处理。"""

        if self.cost_basis <= ZERO:
            return ZERO
        return _quantize(self.realized_pnl / self.cost_basis)


def realized_summary(fills: Sequence[Fill]) -> RealizedSummary:
    """按先进先出把成交配对，算出已实现盈亏与资金变化。"""

    ordered = sorted(fills, key=lambda fill: (fill.ts, fill.fill_id))
    # 每个开仓批次记 [剩余数量, 成交价, 每单位开仓手续费]；开仓手续费计入该批次的
    # 有效成本，平仓时才随配对数量进入已实现盈亏。
    # 批次按标的分别维护：同一策略的多腿组合里，卖出 A 标的不能去平 B 标的的多头。
    long_lots: dict[str, list[list[Decimal]]] = {}
    short_lots: dict[str, list[list[Decimal]]] = {}
    realized = ZERO
    cost_basis = ZERO
    cash_flow: list[CashFlowPoint] = []
    curve: list[ReturnPoint] = []

    for fill in ordered:
        notional = fill.price * fill.qty
        fee = fill.fee.amount
        signed = notional - fee if fill.side == "sell" else -(notional + fee)
        cash_flow.append(CashFlowPoint(at=fill.ts, inst_id=fill.inst_id, amount=signed))

        remaining = fill.qty
        matched = ZERO
        matching = (short_lots if fill.side == "buy" else long_lots).setdefault(fill.inst_id, [])
        while remaining > ZERO and matching:
            lot = matching[0]
            take = min(lot[0], remaining)
            if fill.side == "buy":
                effective_entry = lot[1] - lot[2]
                realized += (effective_entry - fill.price) * take
            else:
                effective_entry = lot[1] + lot[2]
                realized += (fill.price - effective_entry) * take
            cost_basis += lot[1] * take
            matched += take
            remaining -= take
            lot[0] -= take
            if lot[0] == ZERO:
                matching.pop(0)

        if matched > ZERO:
            realized -= fee * matched / fill.qty
            curve.append(ReturnPoint(at=fill.ts, value=_quantize(realized / cost_basis)))
        if remaining > ZERO:
            target = (long_lots if fill.side == "buy" else short_lots).setdefault(fill.inst_id, [])
            target.append([remaining, fill.price, fee / fill.qty])

    net = sum((point.amount for point in cash_flow), ZERO)
    return RealizedSummary(
        realized_pnl=_quantize(realized),
        cost_basis=_quantize(cost_basis),
        net_cash_flow=_quantize(net),
        fill_count=len(ordered),
        cash_flow=tuple(cash_flow),
        curve=tuple(curve),
    )


def build_strategy_journal(
    instance: InstanceRecord,
    *,
    expected_return: Decimal | None,
    expected_source: str,
    snapshot: ExecutionSnapshot,
) -> StrategyJournal:
    """一个策略实例的汇总；实际成交只统计归属到该实例的订单。"""

    order_ids = {
        order.order_id: order.client_order_id for order in snapshot.orders if order.order_id
    }
    owned = set()
    for client_order_id, owner in snapshot.order_owners.items():
        if owner == instance.instance_id:
            owned.add(client_order_id)
    attributed: list[Fill] = []
    for fill in snapshot.fills:
        client_order_id = order_ids.get(fill.order_id, "")
        if client_order_id and client_order_id in owned:
            attributed.append(fill)

    summary = realized_summary(attributed)
    return StrategyJournal(
        instance_id=instance.instance_id,
        strategy_id=instance.strategy_id,
        strategy_version=instance.strategy_version,
        name=instance.name,
        bar=instance.bar,
        lifecycle_status=instance.lifecycle_status,
        execution_mode=instance.execution_mode,
        params=dict(instance.params),
        inst_ids=instance.inst_ids,
        expected_return=None if expected_return is None else _quantize(expected_return),
        expected_source=expected_source,
        actual_return=summary.realized_return,
        actual_source=(
            f"execution:fills:{summary.fill_count}" if summary.fill_count else "execution:no_fills"
        ),
        net_cash_flow=summary.net_cash_flow,
        fill_count=summary.fill_count,
        cash_flow=summary.cash_flow,
        actual_curve=summary.curve,
    )


def build_journal(
    instances: Sequence[InstanceRecord],
    expectations: Mapping[str, tuple[Decimal | None, str]],
    snapshot: ExecutionSnapshot,
) -> JournalView:
    """把实例、回测预期与执行快照合成一份只读视图。

    `expectations` 以实例标识为键，值是（预期收益，来源）二元组；缺失的实例按
    「没有回测」处理，预期收益为 `None`、来源为 `backtest:none`。
    """

    strategies = tuple(
        build_strategy_journal(
            instance,
            expected_return=expectations.get(instance.instance_id, (None, "backtest:none"))[0],
            expected_source=expectations.get(instance.instance_id, (None, "backtest:none"))[1],
            snapshot=snapshot,
        )
        for instance in instances
    )
    entries = _entries(snapshot)
    return JournalView(
        mode=snapshot.mode,
        strategies=strategies,
        positions=snapshot.positions,
        orders=snapshot.orders,
        fills=snapshot.fills,
        signals=snapshot.signals,
        entries=entries,
        order_owners=snapshot.order_owners,
    )


def _entries(snapshot: ExecutionSnapshot) -> tuple[JournalEntry, ...]:
    """日志条目全部由已有事实派生：信号、订单、成交，以及调用方补的条目。"""

    entries = list(snapshot.entries)
    for signal in snapshot.signals:
        entries.append(
            JournalEntry(
                entry_id=f"signal:{signal.signal_id}",
                category="signal",
                message=(f"策略 {signal.instance_id} 在 {signal.inst_id} 给出 {signal.side} 信号"),
                inst_id=signal.inst_id,
                created_at=signal.generated_at,
            )
        )
    for order in snapshot.orders:
        entries.append(_order_entry(order))
    for fill in snapshot.fills:
        entries.append(
            JournalEntry(
                entry_id=f"fill:{fill.fill_id or fill.order_id}",
                category="fill",
                message=(
                    f"成交 {fill.side} {_text(fill.qty)} {fill.inst_id} @ {_text(fill.price)}"
                ),
                inst_id=fill.inst_id,
                created_at=fill.ts,
            )
        )
    entries.sort(key=lambda entry: (entry.created_at, entry.entry_id), reverse=True)
    return tuple(entries)


def _order_entry(order: Order) -> JournalEntry:
    price = "" if order.price is None else f" @ {_text(order.price)}"
    return JournalEntry(
        entry_id=f"order:{order.client_order_id}",
        category="order",
        message=(f"订单 {order.side} {_text(order.qty)} {order.inst_id}{price} → {order.status}"),
        inst_id=order.inst_id,
        created_at=order.created_at,
    )


def _quantize(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = max(context.prec, 40)
        return value.quantize(_QUANTUM)


def _text(value: Decimal) -> str:
    return format(_quantize(value).normalize(), "f")

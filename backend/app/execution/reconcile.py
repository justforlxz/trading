"""对账：把账户实际持仓与策略虚拟持仓逐标比较，产出差额清单。

## 只读

本模块**只比较、不修正**：不写任何一侧的数量或成本，也不自动下单。实盘的修正走
人工确认，paper 的修正由调用方显式调用。清单里的每一项都带 `as_of`，说明它看到的
是哪一刻的事实。

## 两类实际持仓，同一种形状

实际持仓由 T5.2 归一成 `AccountPosition`：SWAP 读持仓接口，SPOT 由余额明细推导
（可用量 + 冻结量）。比较时只读 `product_key` / `side` / `qty` / `avg_cost`，不看
`inst_type`，因此两类持仓共用同一套规则。

## 差额口径

- 同一个 `product_key` 的同一个方向（`long` / `short`）算一项；这不是把多空相减，
  对冲模式下两条腿各自保留。
- `qty_diff = 实际数量 - 虚拟数量`，`qty_diff_pct = qty_diff / |虚拟数量| × 100`。
  虚拟数量为 0 时百分比是**无定义**（`None`），不是 0，也不是 100。
- 数量相同但两侧成本都已知且不同，同样是一项差额（数量差为 0、百分比为 0）。
- 成本 0 在上游表示「未知」（T5.2 的现货口径），清单里按 `None` 输出，也不参与
  成本比较；不用 0 冒充一个可比较的成本。

## 成因归类

清单里的 `cause` 只根据调用方给出的证据判断，不猜：

| 取值 | 判据 |
| --- | --- |
| `partial_fill` | 该产品有仍处于 `partially_filled` 的本地订单（订单还没走完） |
| `unsynced_fill` | 该产品有已取到、但还没记进虚拟账本的成交（`unapplied_fills`） |
| `manual_intervention` | 两侧都有这条持仓，且没有任何订单/成交证据 |
| `exchange_side_unknown` | 只有一侧有这条持仓，且没有任何订单/成交证据 |

`partial_fill` 优先于 `unsynced_fill`：部分成交的订单通常同时带着已成交的部分，
先把「订单还没走完」这个事实说清楚。恢复流程把成交记进虚拟账本后，这一项自然消失。

已撤单、已失败或已全部成交的订单即使有过部分成交，也不再算「订单还没走完」：它们
的成交要靠 `unapplied_fills` 判成 `unsynced_fill`，否则操作者会等一张永远不会再成交
的订单。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.core import Fill, TradePort, ValidationError
from app.execution.orders import STATUS_PARTIALLY_FILLED, Order
from app.execution.positions import (
    NET_POS_SIDE,
    SIDE_LONG,
    SIDE_SHORT,
    AccountPosition,
    from_venue_position,
)
from app.instrument import Instrument, trading_rules

__all__ = [
    "CAUSES",
    "CAUSE_EXCHANGE_SIDE_UNKNOWN",
    "CAUSE_MANUAL_INTERVENTION",
    "CAUSE_PARTIAL_FILL",
    "CAUSE_UNSYNCED_FILL",
    "PositionDifference",
    "ReconcileHolding",
    "ReconciliationReport",
    "difference_percent",
    "fetch_actual_positions",
    "reconcile_positions",
]

CAUSE_UNSYNCED_FILL = "unsynced_fill"
CAUSE_PARTIAL_FILL = "partial_fill"
CAUSE_MANUAL_INTERVENTION = "manual_intervention"
CAUSE_EXCHANGE_SIDE_UNKNOWN = "exchange_side_unknown"
CAUSES = frozenset(
    {
        CAUSE_UNSYNCED_FILL,
        CAUSE_PARTIAL_FILL,
        CAUSE_MANUAL_INTERVENTION,
        CAUSE_EXCHANGE_SIDE_UNKNOWN,
    }
)

ZERO = Decimal(0)
HUNDRED = Decimal(100)
_SIDES = frozenset({SIDE_LONG, SIDE_SHORT})
_Key = tuple[str, str]


@dataclass(frozen=True, slots=True)
class ReconcileHolding:
    """虚拟账本里的一条当前持仓，只保留对账需要的四个字段。

    `inst_type` 只用于展示与排查，不参与比较：同一产品的现货与永续在持仓这一层按
    产品比较，与 T5.2 的口径一致。
    """

    product_key: str
    inst_type: str
    side: str
    qty: Decimal
    avg_cost: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.product_key, str) or not self.product_key.strip():
            raise ValidationError("对账持仓必须给出 product_key")
        if not isinstance(self.inst_type, str) or not self.inst_type.strip():
            raise ValidationError("对账持仓必须给出 inst_type")
        if self.side not in _SIDES:
            raise ValidationError(f"对账持仓方向必须是 {sorted(_SIDES)}, 实际 {self.side!r}")
        if not isinstance(self.qty, Decimal) or not self.qty.is_finite() or self.qty <= ZERO:
            raise ValidationError(f"对账持仓数量必须是正有限数, 实际 {self.qty!r}")
        if (
            not isinstance(self.avg_cost, Decimal)
            or not self.avg_cost.is_finite()
            or self.avg_cost < ZERO
        ):
            raise ValidationError(f"对账持仓成本不能为负, 实际 {self.avg_cost!r}")


@dataclass(frozen=True, slots=True)
class PositionDifference:
    """一条差额；数量与成本两侧都保留，方便人工核对后再决定怎么修正。"""

    product_key: str
    side: str
    actual_qty: Decimal
    actual_avg_cost: Decimal | None
    virtual_qty: Decimal
    virtual_avg_cost: Decimal | None
    qty_diff: Decimal
    qty_diff_pct: Decimal | None
    cause: str
    as_of: datetime

    def __post_init__(self) -> None:
        if self.cause not in CAUSES:
            raise ValidationError(f"未知的差额成因 {self.cause!r}")
        if self.side not in _SIDES:
            raise ValidationError(f"差额方向必须是 {sorted(_SIDES)}, 实际 {self.side!r}")
        if self.as_of.tzinfo is None:
            raise ValidationError("差额的 as_of 必须带时区")


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """一次对账的完整结果；`differences` 为空即两侧一致。"""

    differences: tuple[PositionDifference, ...] = ()
    checked_products: tuple[str, ...] = ()
    as_of: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "differences", tuple(self.differences))
        object.__setattr__(self, "checked_products", tuple(self.checked_products))

    @property
    def balanced(self) -> bool:
        """两侧是否一致。"""

        return not self.differences


def difference_percent(actual_qty: Decimal, virtual_qty: Decimal) -> Decimal | None:
    """差额百分比（`20` 表示 20%）；虚拟数量为 0 时返回 `None`。

    分母取虚拟数量的绝对值，因此空头腿也能得到正数分母。虚拟侧为 0 时百分比没有
    定义：任何实数都能被说成「增长了无穷倍」，清单里如实记无定义。
    """

    for value in (actual_qty, virtual_qty):
        if not isinstance(value, Decimal) or not value.is_finite() or value < ZERO:
            raise ValidationError(f"对账数量必须是非负有限 Decimal, 实际 {value!r}")
    if virtual_qty == ZERO:
        return None
    return (actual_qty - virtual_qty) / abs(virtual_qty) * HUNDRED


def fetch_actual_positions(
    trade: TradePort,
    instruments: Sequence[Instrument],
) -> tuple[AccountPosition, ...]:
    """读交易所侧的实际持仓并归一成 `AccountPosition`。

    两条来源都在交易所适配层完成（SWAP 持仓接口、SPOT 余额明细），本函数只负责
    「`inst_id` → 标的行」的解析与形状归一。上游返回了本地标的表没有的持仓时报错，
    不猜产品键：对不上的持仓正是人工要看的差异，不能在这里被静默丢掉。
    """

    rows = {instrument.symbol: instrument for instrument in instruments}
    positions: list[AccountPosition] = []
    for position in trade.positions():
        instrument = rows.get(position.inst_id)
        if instrument is None:
            raise ValidationError(
                f"交易所有 {position.inst_id} 的持仓, 但本地标的表没有这一行, 无法对账"
            )
        # `TradePort.positions()` 只给出带符号数量，没有对冲腿与保证金字段。
        # 永续按单向模式归一（方向由数量符号决定），现货四个永续字段保持 None。
        pos_side = NET_POS_SIDE if trading_rules(instrument.inst_type).has_margin else None
        positions.append(from_venue_position(position, instrument, pos_side=pos_side))
    return tuple(sorted(positions, key=lambda item: (item.product_key, item.inst_type, item.side)))


def reconcile_positions(
    actual: Sequence[AccountPosition],
    virtual: Sequence[ReconcileHolding],
    *,
    as_of: datetime,
    orders: Sequence[Order] = (),
    unapplied_fills: Sequence[Fill] = (),
    instruments: Sequence[Instrument] = (),
) -> ReconciliationReport:
    """逐标比较实际持仓与虚拟持仓，返回差额清单（纯函数，只读）。

    `orders` 与 `unapplied_fills` 只用于成因归类：前者说明订单是否部分成交，后者
    说明交易所已经发生、但还没记进虚拟账本的成交。两者都不参与数量计算。
    """

    if as_of.tzinfo is None:
        raise ValidationError("对账时间必须带时区")

    actual_by_key = _aggregate_actual(actual)
    virtual_by_key = _aggregate_virtual(virtual)
    keys = sorted(set(actual_by_key) | set(virtual_by_key))
    evidence = _evidence(orders, unapplied_fills, instruments)

    differences: list[PositionDifference] = []
    for key in keys:
        actual_position = actual_by_key.get(key)
        virtual_position = virtual_by_key.get(key)
        actual_qty = actual_position.qty if actual_position is not None else ZERO
        virtual_qty = virtual_position.qty if virtual_position is not None else ZERO
        qty_diff = actual_qty - virtual_qty
        cost_differs = _cost_differs(actual_position, virtual_position)
        if qty_diff == ZERO and not cost_differs:
            continue
        differences.append(
            PositionDifference(
                product_key=key[0],
                side=key[1],
                actual_qty=actual_qty,
                actual_avg_cost=_known_cost(actual_position),
                virtual_qty=virtual_qty,
                virtual_avg_cost=_known_cost(virtual_position),
                qty_diff=qty_diff,
                qty_diff_pct=difference_percent(actual_qty, virtual_qty),
                cause=_cause(key[0], actual_position, virtual_position, evidence),
                as_of=as_of,
            )
        )

    return ReconciliationReport(
        differences=tuple(differences),
        checked_products=tuple(sorted({key[0] for key in keys})),
        as_of=as_of,
    )


def _aggregate_actual(
    positions: Sequence[AccountPosition],
) -> dict[_Key, _Aggregate]:
    return _aggregate(
        (position.product_key, position.side, position.qty, position.avg_cost)
        for position in positions
    )


def _aggregate_virtual(
    positions: Sequence[ReconcileHolding],
) -> dict[_Key, _Aggregate]:
    return _aggregate(
        (position.product_key, position.side, position.qty, position.avg_cost)
        for position in positions
    )


def _aggregate(
    rows: Iterable[tuple[str, str, Decimal, Decimal]],
) -> dict[_Key, _Aggregate]:
    grouped: dict[_Key, list[tuple[Decimal, Decimal]]] = {}
    for product_key, side, qty, avg_cost in rows:
        grouped.setdefault((product_key, side), []).append((qty, avg_cost))

    aggregated: dict[_Key, _Aggregate] = {}
    for (product_key, side), parts in grouped.items():
        total = sum((qty for qty, _cost in parts), ZERO)
        known_qty = sum((qty for qty, cost in parts if cost > ZERO), ZERO)
        if total > ZERO and known_qty == total:
            cost = sum((qty * price for qty, price in parts), ZERO) / total
        else:
            cost = ZERO
        aggregated[(product_key, side)] = _Aggregate(
            product_key=product_key,
            side=side,
            qty=total,
            avg_cost=cost,
        )
    return aggregated


@dataclass(frozen=True, slots=True)
class _Aggregate:
    """同一产品同一方向的所有形态合起来的一条持仓。

    现货与永续是同一产品的两种形态，T5.2 约定持仓按产品比较，因此这里把它们相加。
    成本只在全部数量都有已知成本时才给出加权值；一部分未知就整体记 0（未知），
    不用已知部分冒充整条持仓的成本。
    """

    product_key: str
    side: str
    qty: Decimal
    avg_cost: Decimal


@dataclass(frozen=True, slots=True)
class _Evidence:
    partial_products: frozenset[str]
    unapplied_products: frozenset[str]


def _evidence(
    orders: Sequence[Order],
    unapplied_fills: Sequence[Fill],
    instruments: Sequence[Instrument],
) -> _Evidence:
    product_by_inst = {instrument.symbol: instrument.product_key for instrument in instruments}
    partial: set[str] = set()
    for order in orders:
        product_key = product_by_inst.get(order.inst_id)
        if product_key is None:
            continue
        if order.status == STATUS_PARTIALLY_FILLED:
            partial.add(product_key)
    unapplied: set[str] = set()
    for fill in unapplied_fills:
        product_key = product_by_inst.get(fill.inst_id)
        if product_key is not None:
            unapplied.add(product_key)
    return _Evidence(
        partial_products=frozenset(partial),
        unapplied_products=frozenset(unapplied),
    )


def _cause(
    product_key: str,
    actual: _Aggregate | None,
    virtual: _Aggregate | None,
    evidence: _Evidence,
) -> str:
    if product_key in evidence.partial_products:
        return CAUSE_PARTIAL_FILL
    if product_key in evidence.unapplied_products:
        return CAUSE_UNSYNCED_FILL
    if actual is not None and virtual is not None:
        return CAUSE_MANUAL_INTERVENTION
    return CAUSE_EXCHANGE_SIDE_UNKNOWN


def _known_cost(position: _Aggregate | None) -> Decimal | None:
    """成本 0 表示未知（T5.2 的现货口径），清单里按 `None` 输出。"""

    if position is None or position.avg_cost == ZERO:
        return None
    return position.avg_cost


def _cost_differs(
    actual: _Aggregate | None,
    virtual: _Aggregate | None,
) -> bool:
    if actual is None or virtual is None:
        return False
    if actual.avg_cost == ZERO or virtual.avg_cost == ZERO:
        return False
    return actual.avg_cost != virtual.avg_cost

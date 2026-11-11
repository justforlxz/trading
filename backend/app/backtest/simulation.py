"""撮合与调仓（纯函数）：把「目标权重与当前持仓的差额」换成增量订单，再换成成交。

三条口径固定在本模块，不随调用方变化：

- 目标数量一律走 `app.strategy.target_quantity`，本模块不另写一套换算；
- 成交价 = 该 bar 的执行参考价按成交方向加滑点（买入抬高、卖出压低），手续费按成交
  名义金额逐腿计提；滑点金额单独记账用于成本归因，不从收益里二次扣减；
- 同一 bar 内止盈与止损都触发时按止损结算。这是默认歧义规则，`resolve_exit` 是它
  的唯一实现处。

数量单位到名义金额的乘数按类别查表：现货是标的币数量，乘数为 1；永续是合约张数，
乘数是合约面值 `ct_val`。本模块不判断类别，只读 `qty_unit`。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from app.backtest.costs import BPS, CostModel, execution_price
from app.backtest.errors import MissingInstrumentError
from app.core import InstrumentRef, InvariantViolation, ValidationError
from app.instrument import trading_rules
from app.strategy import TargetPortfolio, target_quantity

__all__ = [
    "ExecutionResult",
    "LegCost",
    "LegExit",
    "LegFill",
    "LegOrder",
    "LegPosition",
    "Settlement",
    "execute_orders",
    "plan_orders",
    "resolve_exit",
]

LONG = "long"
SHORT = "short"
SIDES = frozenset({LONG, SHORT})

ONE = Decimal(1)
ZERO = Decimal(0)

#: 数量单位 → 名义金额乘数。`contract` 读标的自身的合约面值，`base` 直接相乘。
_UNIT_CONTRACT = "contract"


@dataclass(frozen=True, slots=True)
class LegPosition:
    """一条腿上的当前持仓。

    `qty` 恒为非负，方向由 `side` 表达，避免「负数量」与「空头」在某处被当成两件事。
    `entry_price` 是含滑点的成交均价：加仓时按数量加权，减仓不改变它。
    `multiplier` 把数量换成名义金额（现货 1、永续 `ct_val`），持仓期间不变。
    """

    product_key: str
    side: str
    qty: Decimal
    entry_price: Decimal
    entry_time: datetime
    multiplier: Decimal

    def __post_init__(self) -> None:
        if not self.product_key.strip():
            raise ValidationError("持仓的 product_key 不能为空")
        if self.side not in SIDES:
            raise ValidationError(f"持仓的 side 必须是 {sorted(SIDES)}, 实际 {self.side!r}")
        require_positive(self.qty, "持仓数量")
        require_positive(self.entry_price, "持仓开仓价")
        require_positive(self.multiplier, "持仓乘数")
        if self.entry_time.tzinfo is None:
            raise ValidationError("持仓的 entry_time 必须带时区")

    def notional(self, price: Decimal) -> Decimal:
        """按给定价格计算的持仓名义金额（恒为正）。"""

        return self.qty * Decimal(price) * self.multiplier

    def unrealized(self, price: Decimal) -> Decimal:
        """按给定价格计算的浮动盈亏；多头涨为正，空头跌为正。"""

        sign = ONE if self.side == LONG else -ONE
        return sign * (Decimal(price) - self.entry_price) * self.qty * self.multiplier


@dataclass(frozen=True, slots=True)
class LegExit:
    """一条腿的止盈止损价位，绝对价格而不是百分比。

    两个价位都可为空：只设止损、只设止盈或都不设都合法。方向不在这里表达，判定时
    按持仓方向取上下界。
    """

    product_key: str
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.product_key.strip():
            raise ValidationError("退出价位的 product_key 不能为空")
        for name, value in (
            ("stop_loss", self.stop_loss),
            ("take_profit", self.take_profit),
        ):
            if value is not None:
                require_positive(value, name)


@dataclass(frozen=True, slots=True)
class LegOrder:
    """一次增量调仓：把某个标的的持仓朝目标数量移动 `qty`。

    `opening` 区分建仓/加仓与减仓/平仓；方向反转由 `plan_orders` 拆成两条订单，
    因此一条订单永远不会同时跨越零仓位。
    """

    product_key: str
    inst_id: str
    side: str
    qty: Decimal
    opening: bool
    multiplier: Decimal
    reason: str = ""

    def __post_init__(self) -> None:
        if self.side not in SIDES:
            raise ValidationError(f"订单的 side 必须是 {sorted(SIDES)}, 实际 {self.side!r}")
        require_positive(self.qty, "订单数量")
        require_positive(self.multiplier, "订单乘数")

    @property
    def trade_side(self) -> str:
        """成交方向：多头建仓是买、空头建仓是卖，平仓反过来。"""

        if self.side == LONG:
            return "buy" if self.opening else "sell"
        return "sell" if self.opening else "buy"


@dataclass(frozen=True, slots=True)
class LegFill:
    """一次逐腿成交：可追溯到一根 K 线（`bar_open_time`）与一个执行价。"""

    product_key: str
    inst_id: str
    side: str
    qty: Decimal
    price: Decimal
    bar_open_time: datetime
    fee: Decimal
    slippage: Decimal
    opening: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class LegCost:
    """一条腿累计的手续费与滑点；两条腿各记一份，不用组合平均值掩盖。"""

    product_key: str
    inst_id: str
    fee: Decimal
    slippage: Decimal


@dataclass(frozen=True, slots=True)
class Settlement:
    """结算入口的输入：这一根 bar 上「资金费与保证金」需要的全部状态。

    `prices` 是本次结算使用的参考价（与执行模型一致）。返回值是现金变动，负数表示
    从组合扣款。T4.5 交付的实现接收本对象；本节点只负责在正确的时刻调用它。
    """

    moment: datetime
    equity: Decimal
    positions: tuple[LegPosition, ...]
    prices: Mapping[str, Decimal]


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """一组订单执行后的状态增量。"""

    positions: Mapping[str, LegPosition]
    fills: tuple[LegFill, ...]
    realized: Decimal = ZERO
    fees: Decimal = ZERO


def contract_multiplier(instrument: InstrumentRef) -> Decimal:
    """数量单位 → 名义金额乘数。单位只从类别规则表读，本模块不判断类别。"""

    if trading_rules(instrument.inst_type).qty_unit == _UNIT_CONTRACT:
        if instrument.ct_val is None:
            raise ValidationError(f"标的 {instrument.inst_id} 缺少 ct_val, 无法把张数换成名义金额")
        require_positive(instrument.ct_val, "ct_val")
        return instrument.ct_val
    return ONE


def resolve_exit(
    position: LegPosition,
    levels: LegExit,
    *,
    high: Decimal,
    low: Decimal,
) -> tuple[str, Decimal] | None:
    """判定这条腿在本 bar 是否触发退出，返回 `(原因, 成交价)` 或 `None`。

    多头止损在下方、止盈在上方；空头镜像。同一 bar 内两者都触发时按止损结算：成交价
    取止损价，不取 bar 内更有利的极值。

    跳空穿过止损价时不模拟更差的成交价，一律按止损价成交。这一点没有建模，读结果时
    不能把它当成「跳空也能按止损价出场」的结论。
    """

    stop = levels.stop_loss
    take = levels.take_profit
    if position.side == LONG:
        stop_hit = stop is not None and Decimal(low) <= stop
        take_hit = take is not None and Decimal(high) >= take
    else:
        stop_hit = stop is not None and Decimal(high) >= stop
        take_hit = take is not None and Decimal(low) <= take

    if stop_hit:
        return "stop_loss", stop
    if take_hit:
        return "take_profit", take
    return None


def plan_orders(
    target: TargetPortfolio,
    positions: Mapping[str, LegPosition],
    instruments: Mapping[str, InstrumentRef],
    prices: Mapping[str, Decimal],
    capital: Decimal,
) -> tuple[LegOrder, ...]:
    """把目标组合与当前持仓的差额换算成增量订单。

    数量换算调 `target_quantity`，金额基数取调用方给的可用资金。目标里没有的标的
    生成平仓单；方向反转拆成「先平后开」两条，因此一条订单不会跨过零仓位。
    """

    orders: list[LegOrder] = []
    wanted: set[str] = set()
    for leg in target.legs:
        instrument = instrument_for(instruments, leg.product_key)
        price = _price(prices, leg.product_key)
        desired = target_quantity(leg, instrument, price=price, capital=capital).qty
        multiplier = contract_multiplier(instrument)
        wanted.add(leg.product_key)

        current = positions.get(leg.product_key)
        if current is None:
            if desired > ZERO:
                orders.append(
                    _order(leg.product_key, instrument, leg.side, desired, True, multiplier)
                )
            continue
        if current.side != leg.side:
            orders.append(
                _order(
                    leg.product_key,
                    instrument,
                    current.side,
                    current.qty,
                    False,
                    current.multiplier,
                )
            )
            if desired > ZERO:
                orders.append(
                    _order(leg.product_key, instrument, leg.side, desired, True, multiplier)
                )
            continue
        if desired > current.qty:
            orders.append(
                _order(
                    leg.product_key,
                    instrument,
                    leg.side,
                    desired - current.qty,
                    True,
                    current.multiplier,
                )
            )
        elif desired < current.qty:
            orders.append(
                _order(
                    leg.product_key,
                    instrument,
                    current.side,
                    current.qty - desired,
                    False,
                    current.multiplier,
                )
            )

    for product_key, current in positions.items():
        if product_key in wanted:
            continue
        orders.append(
            _order(
                product_key,
                instrument_for(instruments, product_key),
                current.side,
                current.qty,
                False,
                current.multiplier,
                reason="close",
            )
        )
    return tuple(orders)


def execute_orders(
    orders: Iterable[LegOrder],
    positions: Mapping[str, LegPosition],
    *,
    prices: Mapping[str, Decimal],
    costs: CostModel,
    bar_open_time: datetime,
) -> ExecutionResult:
    """把增量订单变成成交：加滑点、按腿记手续费、维护持仓与已实现盈亏。

    加仓时开仓价按数量加权；减仓不改变开仓价。手续费与滑点都按成交名义金额计提，
    滑点已经体现在成交价里，只额外记账不二次扣减。
    """

    updated = dict(positions)
    fills: list[LegFill] = []
    realized = ZERO
    fees = ZERO
    fee_rate = abs(Decimal(costs.fee_bps())) / BPS
    slippage_rate = abs(Decimal(costs.slippage_bps)) / BPS

    for order in orders:
        reference = _price(prices, order.product_key)
        trade_price = execution_price(order.trade_side, reference, costs.slippage_bps)
        notional = order.qty * trade_price * order.multiplier
        fee = fee_rate * notional
        slippage = slippage_rate * order.qty * reference * order.multiplier

        current = updated.get(order.product_key)
        if order.opening:
            if current is not None and current.side != order.side:
                raise InvariantViolation(
                    f"{order.product_key} 的反向持仓必须由两条订单拆开, 不能在建仓单里跨过"
                )
            if current is None:
                updated[order.product_key] = LegPosition(
                    product_key=order.product_key,
                    side=order.side,
                    qty=order.qty,
                    entry_price=trade_price,
                    entry_time=bar_open_time,
                    multiplier=order.multiplier,
                )
            else:
                total = current.qty + order.qty
                blended = (current.entry_price * current.qty + trade_price * order.qty) / total
                updated[order.product_key] = replace(current, qty=total, entry_price=blended)
        else:
            if current is None or current.side != order.side:
                raise InvariantViolation(
                    f"{order.product_key} 的减仓单找不到同方向的持仓, side={order.side}"
                )
            if order.qty > current.qty:
                raise InvariantViolation(
                    f"{order.product_key} 的减仓数量 {order.qty} 超过持仓 {current.qty}"
                )
            sign = ONE if current.side == LONG else -ONE
            realized += sign * (trade_price - current.entry_price) * order.qty * current.multiplier
            remaining = current.qty - order.qty
            if remaining == ZERO:
                del updated[order.product_key]
            else:
                updated[order.product_key] = replace(current, qty=remaining)

        fills.append(
            LegFill(
                product_key=order.product_key,
                inst_id=order.inst_id,
                side=order.side,
                qty=order.qty,
                price=trade_price,
                bar_open_time=bar_open_time,
                fee=fee,
                slippage=slippage,
                opening=order.opening,
                reason=order.reason,
            )
        )
        fees += fee

    return ExecutionResult(positions=updated, fills=tuple(fills), realized=realized, fees=fees)


def _order(
    product_key: str,
    instrument: InstrumentRef,
    side: str,
    qty: Decimal,
    opening: bool,
    multiplier: Decimal,
    *,
    reason: str = "rebalance",
) -> LegOrder:
    return LegOrder(
        product_key=product_key,
        inst_id=instrument.inst_id,
        side=side,
        qty=qty,
        opening=opening,
        multiplier=multiplier,
        reason=reason,
    )


def instrument_for(instruments: Mapping[str, InstrumentRef], product_key: str) -> InstrumentRef:
    """按产品键取标的静态信息。本包内部共用，`engine` 也用它拼成交记录。"""

    instrument = instruments.get(product_key)
    if instrument is None:
        raise MissingInstrumentError(f"标的 {product_key} 没有标的静态信息, 无法换算下单数量")
    return instrument


def _price(prices: Mapping[str, Decimal], product_key: str) -> Decimal:
    price = prices.get(product_key)
    if price is None:
        raise ValidationError(f"标的 {product_key} 在该时刻没有执行价")
    require_positive(price, "执行价")
    return Decimal(price)


def require_positive(value: Decimal, name: str) -> Decimal:
    """入参必须是正的有限 `Decimal`，校验通过后原样返回，便于就地取值。

    本包内部的共用校验，报错文案带上字段名。
    """

    if not isinstance(value, Decimal):
        raise ValidationError(f"{name} 必须是 Decimal, 实际 {type(value).__name__}")
    if not value.is_finite() or value <= ZERO:
        raise ValidationError(f"{name} 必须是正有限数, 实际 {value}")
    return value

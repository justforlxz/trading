"""自动执行：把目标组合换算成增量订单，经风控通过后交给执行层下单。

## 一轮循环做什么

1. 读账户实际持仓（由装配方注入的 `positions_provider` 提供）。
2. **目标组合 → 目标持仓数量**：调用策略域的 `target_quantity`，不在执行层另写一套
   数量换算。
3. **目标持仓 − 当前持仓 = 增量**：按 `product_key` 与所选形态的 `inst_type` 比较，
   多头记正、空头记负。
4. **增量取整**：按 `lot_size` 向下取整；取整后不足 `min_size`（最小下单量）的腿
   直接跳过并记录原因，不构造 0 量订单，也不先下单再等交易所拒绝。
5. **风控在前**：每条增量先交给 `RiskEngine.authorize`；被拒时风控不会返回订单意图，
   本模块也不会自己构造。拒绝会写入 `risk_events`。
6. **下单后同步**：再次读取账户实际持仓。下一轮求差以这次同步到的数量为准，不拿
   「本地以为已经成交的数量」当持仓。

## 边界

- 不实现风控规则（T6.1），只调用风控入口。
- 不做分级处置（T6.5）、不做对账恢复（T6.3）、不做策略计算（T3.x）。
- 默认关闭：未显式开启时一轮也不执行（见 `runtime.py`）。

## 目标组合的形态选择

`instruments` 以 `product_key` 为键，由调用方决定本次交易现货还是永续；同一产品的
另一形态不参与本策略的求差。持仓若属于另一形态，本模块不替调用方改选形态。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal

from app.core import (
    Clock,
    ExecutionRejected,
    InstrumentRef,
    OrderIntent,
    SystemClock,
    UpstreamError,
    ValidationError,
)
from app.execution.model import ExecutionState, Placement
from app.execution.orders import fail, new_order
from app.execution.positions import AccountPosition
from app.execution.runtime import (
    RUNTIME_PAUSED,
    AutoRuntime,
)
from app.execution.service import OrderBackend
from app.risk import RiskContext, RiskEngine, TradeRequest
from app.strategy import TargetPortfolio, target_quantity

__all__ = [
    "AUTO_STATUS_DISABLED",
    "AUTO_STATUS_DUPLICATE",
    "AUTO_STATUS_EXECUTED",
    "AUTO_STATUS_PAUSED",
    "AutoExecutor",
    "AutoRunResult",
    "PositionDelta",
    "RebalancePlan",
    "SkipRecord",
    "reconcile_target",
    "target_key",
]

AUTO_STATUS_DISABLED = "disabled"
AUTO_STATUS_PAUSED = "paused"
AUTO_STATUS_DUPLICATE = "duplicate"
AUTO_STATUS_EXECUTED = "executed"

ZERO = Decimal(0)
SWAP = "SWAP"
LONG = "long"
SHORT = "short"
BUY = "buy"
SELL = "sell"

#: 目标组合的形态选择：`product_key → InstrumentRef`。
Instruments = Mapping[str, InstrumentRef]
#: 账户实际持仓的来源；返回空元组表示明确没有持仓。
PositionsProvider = Callable[[], Sequence[AccountPosition]]


@dataclass(frozen=True, slots=True)
class TargetPosition:
    """一条目标持仓：换算后的数量，方向单独存。"""

    product_key: str
    inst_id: str
    inst_type: str
    side: str
    qty: Decimal

    def __post_init__(self) -> None:
        if self.side not in {LONG, SHORT}:
            raise ValidationError(f"目标持仓方向必须是 long / short, 实际 {self.side!r}")
        if self.qty < ZERO:
            raise ValidationError(f"目标持仓数量不能为负, 实际 {self.qty}")


@dataclass(frozen=True, slots=True)
class PositionDelta:
    """一条需要下单的增量；`side` 是买卖方向。"""

    product_key: str
    inst_id: str
    inst_type: str
    side: str
    qty: Decimal
    reduce_only: bool = False

    def __post_init__(self) -> None:
        if self.side not in {BUY, SELL}:
            raise ValidationError(f"增量方向必须是 buy / sell, 实际 {self.side!r}")
        if self.qty <= ZERO:
            raise ValidationError(f"增量数量必须为正, 实际 {self.qty}")


@dataclass(frozen=True, slots=True)
class SkipRecord:
    """一条被跳过的腿；保留产品键与原因，便于核对为什么没下单。"""

    product_key: str
    inst_id: str
    reason: str

    def __post_init__(self) -> None:
        if not self.product_key.strip():
            raise ValidationError("跳过记录必须给出 product_key")
        if not self.reason.strip():
            raise ValidationError("跳过记录必须给出原因")


@dataclass(frozen=True, slots=True)
class RebalancePlan:
    """一次求差的纯结果：要下的增量与跳过的腿。"""

    target_key: str
    deltas: tuple[PositionDelta, ...] = ()
    skipped: tuple[SkipRecord, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "deltas", tuple(self.deltas))
        object.__setattr__(self, "skipped", tuple(self.skipped))


@dataclass(frozen=True, slots=True)
class RiskRejection:
    """一条被风控拒绝的增量；`violations` 是（规则名，说明）对。"""

    product_key: str
    inst_id: str
    violations: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class AutoRunResult:
    """一轮自动执行的结果。`status` 为 disabled / paused / duplicate / executed。"""

    status: str
    target_key: str = ""
    intents: tuple[OrderIntent, ...] = ()
    placements: tuple[Placement, ...] = ()
    skipped: tuple[SkipRecord, ...] = ()
    rejections: tuple[RiskRejection, ...] = ()
    synced_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("intents", "placements", "skipped", "rejections"):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    @property
    def executed(self) -> bool:
        return self.status == AUTO_STATUS_EXECUTED


def target_key(instance_id: str, target: TargetPortfolio) -> str:
    """同一策略实例、同一 `as_of`、同一目标组合得到同一个键。"""

    if not isinstance(instance_id, str) or not instance_id.strip():
        raise ValidationError("自动执行必须给出策略实例")
    legs = sorted(
        f"{leg.product_key}:{leg.side}:{format(leg.target_weight.normalize(), 'f')}"
        for leg in target.legs
    )
    payload = "|".join((instance_id, target.as_of.isoformat(), *legs))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def reconcile_target(
    *,
    instance_id: str,
    target: TargetPortfolio,
    positions: Sequence[AccountPosition],
    instruments: Instruments,
    prices: Mapping[str, Decimal],
    capital: Decimal,
) -> RebalancePlan:
    """目标组合与账户实际持仓求差，返回可下增量与跳过记录（纯函数）。

    - `positions` 是账户实际持仓，不是策略虚拟持仓。
    - `instruments` 决定同一产品本次使用哪种形态；另一形态的持仓不参与比较。
    - 目标里没有、但账户里仍持有的产品，目标数量按 0 处理（平仓）；无法确定标的或
      精度的持仓只记录跳过原因，不猜一个数量下单。
    """

    plan_key = target_key(instance_id, target)
    skipped: list[SkipRecord] = []
    target_positions: list[TargetPosition] = []
    attempted_products: set[str] = set()

    for leg in target.legs:
        attempted_products.add(leg.product_key)
        instrument = instruments.get(leg.product_key)
        if instrument is None:
            skipped.append(
                SkipRecord(
                    product_key=leg.product_key,
                    inst_id="",
                    reason=f"目标腿 {leg.product_key} 没有对应的标的",
                )
            )
            continue
        if leg.target_weight == ZERO:
            target_positions.append(
                TargetPosition(
                    product_key=leg.product_key,
                    inst_id=instrument.inst_id,
                    inst_type=instrument.inst_type,
                    side=leg.side,
                    qty=ZERO,
                )
            )
            continue
        price = prices.get(instrument.inst_id)
        if price is None:
            skipped.append(
                SkipRecord(
                    product_key=leg.product_key,
                    inst_id=instrument.inst_id,
                    reason=f"标的 {instrument.inst_id} 没有价格, 无法换算目标数量",
                )
            )
            continue
        try:
            quantity = target_quantity(leg, instrument, price=price, capital=capital).qty
        except ValidationError as exc:
            skipped.append(
                SkipRecord(
                    product_key=leg.product_key,
                    inst_id=instrument.inst_id,
                    reason=str(exc),
                )
            )
            continue
        if quantity <= ZERO:
            skipped.append(
                SkipRecord(
                    product_key=leg.product_key,
                    inst_id=instrument.inst_id,
                    reason=f"目标数量按 lot_size {instrument.lot_size} 取整后为 0",
                )
            )
            continue
        target_positions.append(
            TargetPosition(
                product_key=leg.product_key,
                inst_id=instrument.inst_id,
                inst_type=instrument.inst_type,
                side=leg.side,
                qty=quantity,
            )
        )

    current = _signed_positions(positions)
    deltas: list[PositionDelta] = []

    for target_position in target_positions:
        key = (target_position.product_key, target_position.inst_type)
        signed_current = current.pop(key, ZERO)
        signed_target = _signed(target_position.side, target_position.qty)
        delta = _delta(
            target_position.product_key,
            target_position.inst_id,
            target_position.inst_type,
            signed_current,
            signed_target,
            instruments[target_position.product_key],
            skipped,
        )
        if delta is not None:
            deltas.append(delta)

    for (product_key, inst_type), signed_current in sorted(current.items()):
        if signed_current == ZERO:
            continue
        instrument = instruments.get(product_key)
        if instrument is None:
            if product_key not in attempted_products:
                skipped.append(
                    SkipRecord(
                        product_key=product_key,
                        inst_id="",
                        reason=f"持仓 {product_key} 没有对应的标的, 无法平仓",
                    )
                )
            continue
        if instrument.inst_type != inst_type:
            skipped.append(
                SkipRecord(
                    product_key=product_key,
                    inst_id=instrument.inst_id,
                    reason=(
                        f"持仓形态 {inst_type} 与本次目标形态 {instrument.inst_type} 不一致,"
                        " 本轮不调整"
                    ),
                )
            )
            continue
        delta = _delta(
            product_key,
            instrument.inst_id,
            inst_type,
            signed_current,
            ZERO,
            instrument,
            skipped,
        )
        if delta is not None:
            deltas.append(delta)

    return RebalancePlan(target_key=plan_key, deltas=tuple(deltas), skipped=tuple(skipped))


def _signed_positions(positions: Sequence[AccountPosition]) -> dict[tuple[str, str], Decimal]:
    """按（产品，形态）汇总带符号持仓；多头为正、空头为负。"""

    totals: dict[tuple[str, str], Decimal] = {}
    for position in positions:
        if not isinstance(position, AccountPosition):
            raise ValidationError(f"账户持仓只能是 AccountPosition, 实际 {type(position).__name__}")
        key = (position.product_key, position.inst_type)
        totals[key] = totals.get(key, ZERO) + _signed(position.side, position.qty)
    return totals


def _signed(side: str, qty: Decimal) -> Decimal:
    return qty if side == LONG else -qty


def _delta(
    product_key: str,
    inst_id: str,
    inst_type: str,
    signed_current: Decimal,
    signed_target: Decimal,
    instrument: InstrumentRef,
    skipped: list[SkipRecord],
) -> PositionDelta | None:
    """把带符号的差换成正的买卖数量；不足最小下单量时记录跳过。"""

    signed_delta = signed_target - signed_current
    if signed_delta == ZERO:
        return None
    qty, reason = _order_quantity(abs(signed_delta), instrument)
    if qty is None:
        skipped.append(
            SkipRecord(product_key=product_key, inst_id=inst_id, reason=reason or "数量不可下单")
        )
        return None
    return PositionDelta(
        product_key=product_key,
        inst_id=inst_id,
        inst_type=inst_type,
        side=BUY if signed_delta > ZERO else SELL,
        qty=qty,
        reduce_only=_reduce_only(inst_type, signed_current, signed_delta),
    )


def _order_quantity(value: Decimal, instrument: InstrumentRef) -> tuple[Decimal | None, str | None]:
    """按 `lot_size` 向下取整，并检查是否达到最小下单量。"""

    lot_size = instrument.lot_size
    if lot_size is None or lot_size <= ZERO:
        return None, f"标的 {instrument.inst_id} 缺少有效的 lot_size, 无法取整"
    min_size = instrument.min_size
    if min_size is None or min_size <= ZERO:
        return None, f"标的 {instrument.inst_id} 缺少有效的 min_size, 无法判断最小下单量"
    steps = (value / lot_size).to_integral_value(rounding=ROUND_FLOOR)
    qty = steps * lot_size
    if qty <= ZERO:
        return None, (f"增量 {value} 按 lot_size {lot_size} 取整后为 0, 低于最小下单量 {min_size}")
    if qty < min_size:
        return None, (
            f"增量 {value} 按 lot_size {lot_size} 取整后 {qty}, 低于最小下单量 {min_size}"
        )
    return qty, None


def _reduce_only(inst_type: str, signed_current: Decimal, signed_delta: Decimal) -> bool:
    """永续的减仓单标记「只减仓」；反手或新开仓不标记。

    现货没有「只减仓」参数，任何情况下都返回 False。
    """

    if inst_type != SWAP or signed_current == ZERO:
        return False
    if (signed_delta > ZERO) == (signed_current > ZERO):
        return False
    return abs(signed_delta) <= abs(signed_current)


class AutoExecutor:
    """按目标组合求差、过风控、下单并同步账户实际持仓的循环。"""

    def __init__(
        self,
        *,
        backend: OrderBackend,
        risk: RiskEngine,
        runtime: AutoRuntime,
        positions_provider: PositionsProvider | None = None,
        clock: Clock | None = None,
    ) -> None:
        if runtime is None:
            raise ValidationError("自动执行必须有运行控制")
        self._backend = backend
        self._risk = risk
        self._runtime = runtime
        self._positions_provider = positions_provider
        self._clock = clock or SystemClock()
        self._state = ExecutionState()
        self._processed: set[str] = set()

    @property
    def state(self) -> ExecutionState:
        """本地已知的订单、成交与账户实际持仓。"""

        return self._state

    @property
    def runtime(self) -> AutoRuntime:
        return self._runtime

    def sync_positions(self) -> None:
        """从注入的持仓来源刷新账户实际持仓；没有来源时保持原值。"""

        if self._positions_provider is None:
            return
        positions = tuple(self._positions_provider())
        self._state = replace(self._state, positions=positions)

    def run(
        self,
        *,
        instance_id: str,
        target: TargetPortfolio,
        instruments: Instruments,
        prices: Mapping[str, Decimal],
        capital: Decimal,
        risk_context: RiskContext,
    ) -> AutoRunResult:
        """执行一轮；未开启、暂停或同一目标已经处理过时直接返回，不产生订单。"""

        if self._runtime.state == RUNTIME_PAUSED:
            return AutoRunResult(status=AUTO_STATUS_PAUSED)
        if not self._runtime.can_trade:
            return AutoRunResult(status=AUTO_STATUS_DISABLED)

        plan_key = target_key(instance_id, target)
        if plan_key in self._processed:
            return AutoRunResult(status=AUTO_STATUS_DUPLICATE, target_key=plan_key)

        now = self._clock.now()
        self.sync_positions()
        plan = reconcile_target(
            instance_id=instance_id,
            target=target,
            positions=self._state.positions,
            instruments=instruments,
            prices=prices,
            capital=capital,
        )

        intents: list[OrderIntent] = []
        placements: list[Placement] = []
        rejections: list[RiskRejection] = []
        skipped = list(plan.skipped)
        orders = list(self._state.orders)

        for delta in plan.deltas:
            mark_price = prices.get(delta.inst_id)
            if mark_price is None:
                skipped.append(
                    SkipRecord(
                        product_key=delta.product_key,
                        inst_id=delta.inst_id,
                        reason=f"标的 {delta.inst_id} 没有价格, 无法提交市价单",
                    )
                )
                continue
            request = TradeRequest(
                instance_id=instance_id,
                inst_id=delta.inst_id,
                side=delta.side,
                order_type="market",
                qty=delta.qty,
                ts=now,
                mark_price=mark_price,
                reduce_only=delta.reduce_only,
                client_order_id=_client_order_id(instance_id, plan_key, delta),
            )
            authorization = self._risk.authorize(request, risk_context)
            if authorization.intent is None:
                rejections.append(
                    RiskRejection(
                        product_key=delta.product_key,
                        inst_id=delta.inst_id,
                        violations=tuple(
                            (violation.rule, violation.detail)
                            for violation in authorization.violations
                        ),
                    )
                )
                continue

            intents.append(authorization.intent)
            try:
                order = self._backend.place(authorization.intent, now=now)
            except (ExecutionRejected, UpstreamError) as exc:
                order = fail(new_order(authorization.intent, now=now), now=now)
                placements.append(
                    Placement(
                        client_order_id=authorization.intent.client_order_id,
                        order=order,
                        error=str(exc),
                    )
                )
            else:
                placements.append(
                    Placement(
                        client_order_id=authorization.intent.client_order_id,
                        order=order,
                    )
                )
            orders.append(order)

        self._state = replace(self._state, orders=tuple(orders))
        self._processed.add(plan_key)
        self.sync_positions()

        return AutoRunResult(
            status=AUTO_STATUS_EXECUTED,
            target_key=plan_key,
            intents=tuple(intents),
            placements=tuple(placements),
            skipped=tuple(skipped),
            rejections=tuple(rejections),
            synced_at=self._clock.now() if self._positions_provider is not None else None,
        )


def _client_order_id(instance_id: str, plan_key: str, delta: PositionDelta) -> str:
    """由实例、目标键、标的、方向与数量派生幂等键；同一条增量重复执行得到同一个键。"""

    payload = "|".join(
        (
            instance_id,
            plan_key,
            delta.inst_id,
            delta.side,
            format(delta.qty, "f"),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

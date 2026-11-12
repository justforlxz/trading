"""执行编排的数据模型：交易计划、确认记录、本地状态与同步结果。

本模块只放**值对象**，不碰数据库、网络与时钟：

- `TradePlan` 是「准备下什么」的不可变快照，确认记录绑定到具体 `plan_id` 与
  `version`，计划改版后旧确认自动失效；
- `ExecutionState` 是本地已知的订单、成交与持仓，同步时以交易所或 paper 账本回写；
- `VenueSnapshot` 是上游一次同步快照，`positions` 为 `None` 表示这次没有拿到持仓，
  与「拿到空持仓」区分开。

订单对象沿用 `app.execution.orders.Order`，不在这里再造一个形状。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.core import Fill, ValidationError
from app.execution.orders import STATUS_FAILED, Order
from app.execution.positions import AccountPosition

__all__ = [
    "ConfirmationRecord",
    "ExecutionState",
    "Placement",
    "PlacementResult",
    "PlanLeg",
    "SyncResult",
    "TradePlan",
    "VenueSnapshot",
]

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class PlanLeg:
    """交易计划的一条腿：下哪个标的、什么方向、多少数量、价格上限与来源策略。

    `price_cap` 为 `None` 表示市价单；有值时表示限价单的价格上限（买入不高于该价，
    卖出不低于该价）。数量已经是按标的精度换算后的可下数量，不在执行层重复取整。

    本项目固定净持仓（`net`），因此计划不需要按对冲模式指定多空腿；持仓方向由交易所
    适配层的默认值补齐，不在计划里重复一份。
    """

    product_key: str
    inst_id: str
    inst_type: str
    side: str
    qty: Decimal
    strategy_id: str
    price_cap: Decimal | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("product_key", self.product_key),
            ("inst_id", self.inst_id),
            ("inst_type", self.inst_type),
            ("strategy_id", self.strategy_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f"计划腿的 {name} 不能为空")
        if self.side not in {"buy", "sell"}:
            raise ValidationError(f"计划腿的 side 必须是 buy 或 sell, 实际 {self.side!r}")
        if not isinstance(self.qty, Decimal) or not self.qty.is_finite() or self.qty <= ZERO:
            raise ValidationError(f"计划腿的数量必须为正的 Decimal, 实际 {self.qty!r}")
        if self.price_cap is not None and (
            not isinstance(self.price_cap, Decimal)
            or not self.price_cap.is_finite()
            or self.price_cap <= ZERO
        ):
            raise ValidationError(f"计划腿的价格上限必须为正, 实际 {self.price_cap!r}")

    @property
    def order_type(self) -> str:
        """有价格上限就是限价单，否则是市价单。"""

        return "limit" if self.price_cap is not None else "market"


@dataclass(frozen=True, slots=True)
class TradePlan:
    """一次人工确认前的完整交易计划。"""

    plan_id: str
    version: int
    as_of: datetime
    legs: tuple[PlanLeg, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.plan_id, str) or not self.plan_id.strip():
            raise ValidationError("交易计划必须给出 plan_id")
        if not isinstance(self.version, int) or self.version < 1:
            raise ValidationError(f"交易计划版本必须是正整数, 实际 {self.version!r}")
        if self.as_of.tzinfo is None:
            raise ValidationError("交易计划的 as_of 必须带时区")
        legs = tuple(self.legs)
        for leg in legs:
            if not isinstance(leg, PlanLeg):
                raise ValidationError(f"计划腿只能是 PlanLeg, 实际 {type(leg).__name__}")
        seen: set[str] = set()
        for leg in legs:
            if leg.inst_id in seen:
                raise ValidationError(f"同一交易计划里标的重复:{leg.inst_id}")
            seen.add(leg.inst_id)
        object.__setattr__(self, "legs", legs)


@dataclass(frozen=True, slots=True)
class ConfirmationRecord:
    """人工确认记录：谁在什么时候确认了哪个版本的哪份计划。

    `plan_digest` 是计划内容的摘要。只绑定 `plan_id` 与 `version` 不够：调用方可能
    沿用同一个版本号重新生成数量或价格不同的计划，摘要能识别这种内容变化。
    """

    plan_id: str
    plan_version: int
    plan_digest: str
    confirmed_by: str
    confirmed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.plan_id, str) or not self.plan_id.strip():
            raise ValidationError("确认记录必须给出 plan_id")
        if not isinstance(self.plan_version, int) or self.plan_version < 1:
            raise ValidationError(f"确认记录的计划版本必须是正整数, 实际 {self.plan_version!r}")
        if not isinstance(self.plan_digest, str) or not self.plan_digest.strip():
            raise ValidationError("确认记录必须给出计划内容摘要")
        if not isinstance(self.confirmed_by, str) or not self.confirmed_by.strip():
            raise ValidationError("确认记录必须给出确认人")
        if self.confirmed_at.tzinfo is None:
            raise ValidationError("确认记录的 confirmed_at 必须带时区")


@dataclass(frozen=True, slots=True)
class ExecutionState:
    """本地已知的执行状态：订单、成交与账户实际持仓。"""

    orders: tuple[Order, ...] = ()
    fills: tuple[Fill, ...] = ()
    positions: tuple[AccountPosition, ...] = ()

    def __post_init__(self) -> None:
        orders = tuple(self.orders)
        fills = tuple(self.fills)
        positions = tuple(self.positions)
        for order in orders:
            if not isinstance(order, Order):
                raise ValidationError(f"本地订单只能是 Order, 实际 {type(order).__name__}")
        for fill in fills:
            if not isinstance(fill, Fill):
                raise ValidationError(f"本地成交只能是 Fill, 实际 {type(fill).__name__}")
        for position in positions:
            if not isinstance(position, AccountPosition):
                raise ValidationError(
                    f"本地持仓只能是 AccountPosition, 实际 {type(position).__name__}"
                )
        order_ids = [order.client_order_id for order in orders]
        if len(order_ids) != len(set(order_ids)):
            raise ValidationError("本地订单的 client_order_id 不能重复")
        fill_ids = [fill.fill_id for fill in fills if fill.fill_id]
        if len(fill_ids) != len(set(fill_ids)):
            raise ValidationError("本地成交的 fill_id 不能重复")
        object.__setattr__(self, "orders", orders)
        object.__setattr__(self, "fills", fills)
        object.__setattr__(self, "positions", positions)

    def order(self, client_order_id: str) -> Order | None:
        """按幂等键找本地订单；没有返回 `None`。"""

        for order in self.orders:
            if order.client_order_id == client_order_id:
                return order
        return None


@dataclass(frozen=True, slots=True)
class VenueSnapshot:
    """一次同步拿到的上游事实。

    `positions` 为 `None` 表示这次没有取持仓，同步保留本地持仓；空元组表示上游明确
    返回「没有持仓」，同步会把本地持仓清空。两种含义不能混用。
    """

    orders: tuple[Order, ...] = ()
    fills: tuple[Fill, ...] = ()
    positions: tuple[AccountPosition, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "orders", tuple(self.orders))
        object.__setattr__(self, "fills", tuple(self.fills))
        if self.positions is not None:
            object.__setattr__(self, "positions", tuple(self.positions))


@dataclass(frozen=True, slots=True)
class SyncResult:
    """同步结果：新的本地状态，以及本次新增、修正、置失败的订单键。"""

    state: ExecutionState
    added_client_order_ids: tuple[str, ...] = ()
    updated_client_order_ids: tuple[str, ...] = ()
    failed_client_order_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "added_client_order_ids",
            "updated_client_order_ids",
            "failed_client_order_ids",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class Placement:
    """一条腿的下单结果。`retry_count` 恒为 0：失败不自动重发。"""

    client_order_id: str
    order: Order
    retry_count: int = 0
    error: str | None = None
    reused: bool = False

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise ValidationError("下单结果必须给出 client_order_id")
        if self.retry_count < 0:
            raise ValidationError(f"重试计数不能为负, 实际 {self.retry_count}")

    @property
    def failed(self) -> bool:
        return self.order.status == STATUS_FAILED


@dataclass(frozen=True, slots=True)
class PlacementResult:
    """一次计划下单的结果集合。"""

    placements: tuple[Placement, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "placements", tuple(self.placements))

    @property
    def orders(self) -> tuple[Order, ...]:
        return tuple(placement.order for placement in self.placements)

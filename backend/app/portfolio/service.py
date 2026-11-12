"""策略级虚拟持仓与全局组合管理的编排：读写账本、分配、敞口与调整申请。

## 账本从成交流水重建

`virtual_fills` 是唯一事实来源，`virtual_positions` 是它的投影：每次记账都把该
（实例，标的）的全部成交按时间顺序重放一遍 FIFO，再把结果写回投影行。投影行不存
批次，因此不会出现「批次与汇总数量各自漂移」的情况；重建的成本是一条标的的成交条数。

## 敞口口径

敞口按**名义价值**（报价币）计：一条持仓的名义价值 = 数量 × 标记价 × 合约面值
（现货面值按 1）。于是：

    净敞口 = Σ多头名义价值 − Σ空头名义价值

与验收里的「多头权重之和减空头权重之和」是同一式子——这里的「权重」取持仓的名义价值，
每个策略以同样的分母（自己的资金预算）折算权重，因此权重之和与名义价值之差只差一个
常数因子，等式两边同时成立。

集中度 = 单一产品净名义价值绝对值的最大值 ÷ 组合权益（各策略资金预算之和）；权益
为 0 时没有可比较的分母，占比记 0。各策略预算不同，权重不能直接跨策略相加当集中度。

## 资金预算与优先级

`allocations` 是唯一存放预算与优先级的地方。实盘授权端点校验过预算为正，批准调整时
不复制第二份预算：预算只经 `record_allocation` 写入。没有分配行的实例预算为 0，
界面如实显示 0，不伪造默认值。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import Conflict, ValidationError
from app.db import session_scope
from app.instrument import Instrument, list_instruments, trading_rules
from app.portfolio.conflict import ExposureLeg, PortfolioConflict, aggregate_exposure
from app.portfolio.ledger import (
    SIDE_LONG,
    SIDE_SHORT,
    LedgerPosition,
    Lot,
    apply_fill,
    unrealized_pnl,
)
from app.portfolio.model import (
    AllocationRow,
    PortfolioAdjustmentRow,
    VirtualFillRow,
    VirtualPositionRow,
)
from app.strategy import InstanceRecord, get_instance, list_instances

__all__ = [
    "AdjustmentRecord",
    "ExposureOverview",
    "StrategyPortfolio",
    "StrategyPortfolioDetail",
    "TargetLegRecord",
    "TargetRecord",
    "VirtualPosition",
    "create_adjustment",
    "decide_adjustment",
    "exposure_overview",
    "get_portfolio",
    "list_adjustments",
    "list_portfolios",
    "record_allocation",
    "record_fill",
]

ZERO = Decimal(0)
ONE = Decimal(1)
UNIT_CONTRACT = "contract"
UNIT_BASE = "base"
PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
DECISIONS = frozenset({APPROVED, REJECTED})
FILL_SIDES = frozenset({"buy", "sell"})
DIRECTIONS = frozenset({SIDE_LONG, SIDE_SHORT})
MAX_LIMIT = 500


@dataclass(frozen=True, slots=True)
class TargetLegRecord:
    """目标组合里的一条腿。`qty` / `unit` 可空表示尚未换算。"""

    inst_id: str
    inst_type: str
    direction: str
    target_weight: Decimal
    qty: Decimal | None = None
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class TargetRecord:
    """一份目标组合；`net_exposure` 由各腿推导，不接受调用方传入。"""

    legs: tuple[TargetLegRecord, ...]
    net_exposure: Decimal


@dataclass(frozen=True, slots=True)
class StrategyPortfolio:
    """组合列表与明细共用的策略级概览。"""

    instance_id: str
    strategy_id: str
    name: str
    lifecycle_status: str
    priority: int
    capital_budget: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    open_positions: int


@dataclass(frozen=True, slots=True)
class VirtualPosition:
    """策略账本里的一条当前持仓（已平仓的行不在这里出现）。"""

    inst_id: str
    inst_type: str
    product_key: str
    direction: str
    qty: Decimal
    unit: str
    avg_cost: Decimal
    mark_price: Decimal
    notional: Decimal
    unrealized_pnl: Decimal
    opened_at: datetime


@dataclass(frozen=True, slots=True)
class StrategyPortfolioDetail:
    portfolio: StrategyPortfolio
    positions: tuple[VirtualPosition, ...]
    target: TargetRecord | None


@dataclass(frozen=True, slots=True)
class AdjustmentRecord:
    adjustment_id: str
    instance_id: str
    status: str
    requested_by: str
    requested_at: datetime
    decided_by: str | None
    decided_at: datetime | None
    note: str | None
    target: TargetRecord


@dataclass(frozen=True, slots=True)
class ExposureOverview:
    gross_exposure: Decimal
    net_exposure: Decimal
    long_exposure: Decimal
    short_exposure: Decimal
    largest_position_share: Decimal
    open_positions: int
    product_count: int
    conflicts: tuple[PortfolioConflict, ...]
    generated_at: datetime


# ------------------------------------------------------------------ 账本写入


def record_fill(
    instance_id: str,
    *,
    inst_id: str,
    side: str,
    qty: Decimal,
    price: Decimal,
    fee: Decimal = ZERO,
    at: datetime | None = None,
) -> VirtualPosition | None:
    """给策略账本记一笔成交；平仓后返回 `None`（当前没有持仓）。

    标记价取这笔成交价：本节点没有行情推送，未实现盈亏的含义是「按最近成交价看」，
    口径写在返回值与接口文档里，不假装是实时行情。
    """

    if side not in FILL_SIDES:
        raise ValidationError(f"成交方向必须是 {sorted(FILL_SIDES)}, 实际 {side!r}")
    instrument = _instrument(inst_id)
    moment = _now() if at is None else at
    if moment.tzinfo is None:
        raise ValidationError("成交时刻必须带时区")
    if get_instance(instance_id) is None:
        raise ValidationError(f"未找到策略实例 {instance_id}")

    with session_scope() as session:
        session.add(
            VirtualFillRow(
                fill_id="vf_" + uuid4().hex[:24],
                instance_id=instance_id,
                inst_id=inst_id,
                side=side,
                qty=qty,
                price=price,
                fee=fee,
                at=moment,
            )
        )
        session.flush()
        ledger = _replay(
            session,
            instance_id,
            inst_id,
            multiplier=_contract_size(instrument),
        )
        _write_projection(session, instance_id, instrument, ledger, mark_price=price, at=moment)

    return _position_view(instrument, ledger, price, moment)


def record_allocation(
    instance_id: str,
    *,
    capital_budget: Decimal,
    priority: int = 0,
) -> None:
    """写入或更新一个实例的资金预算与优先级；不影响已生效目标组合。"""

    if not isinstance(capital_budget, Decimal) or not capital_budget.is_finite():
        raise ValidationError("资金预算必须是有限 Decimal")
    if capital_budget < ZERO:
        raise ValidationError(f"资金预算不能为负, 实际 {capital_budget}")
    if not isinstance(priority, int) or isinstance(priority, bool):
        raise ValidationError(f"优先级必须是整数, 实际 {priority!r}")
    if get_instance(instance_id) is None:
        raise ValidationError(f"未找到策略实例 {instance_id}")

    with session_scope() as session:
        row = session.get(AllocationRow, instance_id)
        if row is None:
            session.add(
                AllocationRow(
                    instance_id=instance_id,
                    priority=priority,
                    capital_budget=capital_budget,
                    target_json=None,
                    updated_at=_now(),
                )
            )
            return
        row.priority = priority
        row.capital_budget = capital_budget
        row.updated_at = _now()


# ------------------------------------------------------------------ 查询


def list_portfolios() -> tuple[tuple[StrategyPortfolio, ...], int]:
    """列出全部策略实例的组合概览，按优先级倒序、实例标识升序。"""

    records, total = list_instances(limit=MAX_LIMIT)
    instruments = _instruments()
    with session_scope() as session:
        allocations = {row.instance_id: row for row in session.scalars(select(AllocationRow))}
        positions = _all_positions(session)

    items = [
        _portfolio(
            record,
            allocations.get(record.instance_id),
            [row for row in positions if row.instance_id == record.instance_id],
            instruments,
        )
        for record in records
    ]
    items.sort(key=lambda item: (-item.priority, item.instance_id))
    return tuple(items), total


def get_portfolio(instance_id: str) -> StrategyPortfolioDetail | None:
    """单个策略的明细；实例不存在返回 `None`。"""

    record = get_instance(instance_id)
    if record is None:
        return None
    instruments = _instruments()
    with session_scope() as session:
        allocation = session.get(AllocationRow, instance_id)
        rows = list(
            session.scalars(
                select(VirtualPositionRow)
                .where(VirtualPositionRow.instance_id == instance_id)
                .order_by(VirtualPositionRow.inst_id)
            )
        )
    portfolio = _portfolio(record, allocation, rows, instruments)
    positions = tuple(view for row in rows if (view := _row_view(row, instruments)) is not None)
    target = None
    if allocation is not None and allocation.target_json is not None:
        target = _target_from_json(allocation.target_json)
    return StrategyPortfolioDetail(portfolio=portfolio, positions=positions, target=target)


def exposure_overview() -> ExposureOverview:
    """全局敞口总览：按各策略预算折算权重后汇总，集中度按名义价值与组合权益计算。"""

    records, _ = list_instances(limit=MAX_LIMIT)
    instruments = _instruments()
    with session_scope() as session:
        allocations = {row.instance_id: row for row in session.scalars(select(AllocationRow))}
        rows = _all_positions(session)

    legs: list[ExposureLeg] = []
    equity = sum(
        (
            allocations[record.instance_id].capital_budget
            if record.instance_id in allocations
            else ZERO
        )
        for record in records
    )
    for record in records:
        budget = (
            allocations[record.instance_id].capital_budget
            if record.instance_id in allocations
            else ZERO
        )
        for row in rows:
            if row.instance_id != record.instance_id:
                continue
            view = _row_view(row, instruments)
            if view is None:
                continue
            weight = view.notional / budget if budget > ZERO else ZERO
            legs.append(
                ExposureLeg(
                    instance_id=record.instance_id,
                    product_key=view.product_key,
                    direction=view.direction,
                    weight=weight,
                    notional=view.notional,
                )
            )
    aggregate = aggregate_exposure(legs, equity=equity)
    return ExposureOverview(
        gross_exposure=aggregate.gross_exposure,
        net_exposure=aggregate.net_exposure,
        long_exposure=aggregate.long_exposure,
        short_exposure=aggregate.short_exposure,
        largest_position_share=aggregate.largest_position_share,
        open_positions=aggregate.open_positions,
        product_count=aggregate.product_count,
        conflicts=aggregate.conflicts,
        generated_at=_now(),
    )


# ------------------------------------------------------------------ 调整申请


def create_adjustment(
    *,
    instance_id: str,
    requested_by: str,
    target: TargetRecord,
    note: str | None = None,
) -> AdjustmentRecord:
    """提交一条调整申请：只写申请，不改生效状态。"""

    if get_instance(instance_id) is None:
        raise ValidationError(f"未找到策略实例 {instance_id}")
    actor = _require_actor(requested_by, "申请人")
    _validate_target(target)
    row = PortfolioAdjustmentRow(
        adjustment_id="adj_" + uuid4().hex[:24],
        instance_id=instance_id,
        status=PENDING,
        requested_by=actor,
        requested_at=_now(),
        decided_by=None,
        decided_at=None,
        note=_optional_text(note),
        decision_note=None,
        target_json=_target_json(target),
    )
    with session_scope() as session:
        session.add(row)
    return _adjustment(row)


def decide_adjustment(
    adjustment_id: str,
    *,
    decision: str,
    decided_by: str,
    note: str | None = None,
) -> AdjustmentRecord | None:
    """批准或驳回一条申请；不存在返回 `None`，已决定过则抛 `Conflict`。

    批准时把目标写进 `allocations.target_json`，与决定人、决定时间在同一次事务里落库：
    「已批准」与「已生效」不会出现一半的中间状态。
    """

    if decision not in DECISIONS:
        raise ValidationError(f"决定必须是 {sorted(DECISIONS)}, 实际 {decision!r}")
    actor = _require_actor(decided_by, "决定人")
    moment = _now()
    with session_scope() as session:
        row = session.get(PortfolioAdjustmentRow, adjustment_id, with_for_update=True)
        if row is None:
            return None
        if row.status != PENDING:
            raise Conflict(f"调整申请 {adjustment_id} 已经是 {row.status}, 不能重复决定")
        row.status = decision
        row.decided_by = actor
        row.decided_at = moment
        row.decision_note = _optional_text(note)
        if decision == APPROVED:
            _apply_target(session, row.instance_id, row.target_json, moment)
        session.flush()
        return _adjustment(row)


def list_adjustments(*, limit: int = 200) -> tuple[tuple[AdjustmentRecord, ...], int]:
    """按申请时间倒序列出调整申请。"""

    if limit < 1:
        raise ValidationError(f"条数上限必须是正整数:{limit}")
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(PortfolioAdjustmentRow)
                .order_by(
                    PortfolioAdjustmentRow.requested_at.desc(),
                    PortfolioAdjustmentRow.adjustment_id,
                )
                .limit(limit)
            )
        )
        total = session.scalar(select(func.count()).select_from(PortfolioAdjustmentRow))
    return tuple(_adjustment(row) for row in rows), total or 0


# ------------------------------------------------------------------ 账本内部


def _replay(
    session: Session,
    instance_id: str,
    inst_id: str,
    *,
    multiplier: Decimal,
) -> LedgerPosition:
    """按数据库写入顺序重放该（实例，标的）的全部成交，得到当前账本状态。"""

    statement = (
        select(VirtualFillRow)
        .where(
            VirtualFillRow.instance_id == instance_id,
            VirtualFillRow.inst_id == inst_id,
        )
        .order_by(VirtualFillRow.seq)
    )
    ledger = LedgerPosition(direction=None, lots=())
    for fill in session.scalars(statement):
        ledger = apply_fill(
            ledger,
            side=fill.side,
            qty=fill.qty,
            price=fill.price,
            fee=fill.fee,
            multiplier=multiplier,
        )
    return ledger


def _write_projection(
    session: Session,
    instance_id: str,
    instrument: Instrument,
    ledger: LedgerPosition,
    *,
    mark_price: Decimal,
    at: datetime,
) -> None:
    """把重放结果写回投影行；成交后总会有这一行（平仓行保留）。"""

    row = session.get(VirtualPositionRow, (instance_id, instrument.symbol))
    if row is None:
        row = VirtualPositionRow(
            instance_id=instance_id,
            inst_id=instrument.symbol,
            inst_type=instrument.inst_type,
            product_key=instrument.product_key,
            direction=None,
            qty=ZERO,
            avg_cost=ZERO,
            mark_price=None,
            realized_pnl=ZERO,
            fees=ZERO,
            opened_at=None,
            updated_at=at,
        )
        session.add(row)
    row.inst_type = instrument.inst_type
    row.product_key = instrument.product_key
    row.direction = ledger.direction
    row.qty = ledger.qty
    row.avg_cost = ledger.avg_cost
    row.mark_price = mark_price
    row.realized_pnl = ledger.realized_pnl
    row.fees = ledger.fees
    row.updated_at = at
    if ledger.direction is not None and row.opened_at is None:
        row.opened_at = at
    if ledger.direction is None:
        row.opened_at = None


def _all_positions(session: Session) -> list[VirtualPositionRow]:
    return list(
        session.scalars(
            select(VirtualPositionRow).order_by(
                VirtualPositionRow.instance_id, VirtualPositionRow.inst_id
            )
        )
    )


def _apply_target(session: Session, instance_id: str, target_json: str, moment: datetime) -> None:
    row = session.get(AllocationRow, instance_id)
    if row is None:
        session.add(
            AllocationRow(
                instance_id=instance_id,
                priority=0,
                capital_budget=ZERO,
                target_json=target_json,
                updated_at=moment,
            )
        )
        return
    row.target_json = target_json
    row.updated_at = moment


# ------------------------------------------------------------------ 视图


def _portfolio(
    record: InstanceRecord,
    allocation: AllocationRow | None,
    rows: Sequence[VirtualPositionRow],
    instruments: Mapping[str, Instrument],
) -> StrategyPortfolio:
    views = [view for row in rows if (view := _row_view(row, instruments)) is not None]
    long_money = sum((view.notional for view in views if view.direction == SIDE_LONG), ZERO)
    short_money = sum((view.notional for view in views if view.direction != SIDE_LONG), ZERO)
    return StrategyPortfolio(
        instance_id=record.instance_id,
        strategy_id=record.strategy_id,
        name=record.name,
        lifecycle_status=record.lifecycle_status,
        priority=allocation.priority if allocation is not None else 0,
        capital_budget=allocation.capital_budget if allocation is not None else ZERO,
        gross_exposure=long_money + short_money,
        net_exposure=long_money - short_money,
        unrealized_pnl=sum((view.unrealized_pnl for view in views), ZERO),
        realized_pnl=sum((row.realized_pnl for row in rows), ZERO),
        open_positions=len(views),
    )


def _row_view(
    row: VirtualPositionRow, instruments: Mapping[str, Instrument]
) -> VirtualPosition | None:
    if row.qty == ZERO or row.direction is None:
        return None
    instrument = instruments.get(row.inst_id)
    if instrument is None:
        raise ValidationError(f"虚拟持仓的标的 {row.inst_id} 不在标的表里, 无法计算名义价值")
    mark = row.mark_price if row.mark_price is not None else row.avg_cost
    ledger = LedgerPosition(
        direction=row.direction,
        lots=(Lot(row.qty, row.avg_cost),),
        realized_pnl=row.realized_pnl,
        fees=row.fees,
    )
    return VirtualPosition(
        inst_id=row.inst_id,
        inst_type=row.inst_type,
        product_key=row.product_key,
        direction=row.direction,
        qty=row.qty,
        unit=trading_rules(row.inst_type).qty_unit,
        avg_cost=row.avg_cost,
        mark_price=mark,
        notional=_notional(instrument, row.qty, mark),
        unrealized_pnl=unrealized_pnl(ledger, mark, _contract_size(instrument)),
        opened_at=row.opened_at if row.opened_at is not None else row.updated_at,
    )


def _position_view(
    instrument: Instrument,
    ledger: LedgerPosition,
    price: Decimal,
    at: datetime,
) -> VirtualPosition | None:
    if ledger.direction is None:
        return None
    return VirtualPosition(
        inst_id=instrument.symbol,
        inst_type=instrument.inst_type,
        product_key=instrument.product_key,
        direction=ledger.direction,
        qty=ledger.qty,
        unit=trading_rules(instrument.inst_type).qty_unit,
        avg_cost=ledger.avg_cost,
        mark_price=price,
        notional=_notional(instrument, ledger.qty, price),
        unrealized_pnl=unrealized_pnl(ledger, price, _contract_size(instrument)),
        opened_at=at,
    )


def _notional(instrument: Instrument, qty: Decimal, price: Decimal) -> Decimal:
    """名义价值：现货按数量 × 价格；合约按张数 × 合约面值 × 价格。"""

    return qty * _contract_size(instrument) * price


def _contract_size(instrument: Instrument) -> Decimal:
    """数量乘以它才变成标的数量的乘数：永续取合约面值，现货取 1。"""

    unit = trading_rules(instrument.inst_type).qty_unit
    if unit == UNIT_CONTRACT:
        if instrument.ct_val is None:
            raise ValidationError(f"标的 {instrument.symbol} 缺少合约面值, 无法计算盈亏")
        if instrument.ct_val <= ZERO:
            raise ValidationError(f"标的 {instrument.symbol} 的合约面值必须为正")
        return instrument.ct_val
    if unit == UNIT_BASE:
        return ONE
    raise ValidationError(f"标的 {instrument.symbol} 的数量单位 {unit!r} 没有盈亏换算公式")


def _instruments() -> dict[str, Instrument]:
    return {row.symbol: row for row in list_instruments()}


def _instrument(inst_id: str) -> Instrument:
    row = _instruments().get(inst_id)
    if row is None:
        raise ValidationError(f"未找到标的 {inst_id}")
    return row


# ------------------------------------------------------------------ 目标组合 JSON


def _target_json(target: TargetRecord) -> str:
    return json.dumps(
        {
            "legs": [
                {
                    "inst_id": leg.inst_id,
                    "inst_type": leg.inst_type,
                    "direction": leg.direction,
                    "target_weight": str(leg.target_weight),
                    "qty": None if leg.qty is None else str(leg.qty),
                    "unit": leg.unit,
                }
                for leg in target.legs
            ],
            "net_exposure": str(target.net_exposure),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _target_from_json(text: str) -> TargetRecord:
    payload = json.loads(text)
    legs = tuple(
        TargetLegRecord(
            inst_id=item["inst_id"],
            inst_type=item["inst_type"],
            direction=item["direction"],
            target_weight=Decimal(item["target_weight"]),
            qty=None if item.get("qty") is None else Decimal(item["qty"]),
            unit=item.get("unit"),
        )
        for item in payload["legs"]
    )
    return TargetRecord(legs=legs, net_exposure=Decimal(payload["net_exposure"]))


def _validate_target(target: TargetRecord) -> None:
    seen: set[str] = set()
    computed = ZERO
    for leg in target.legs:
        if not leg.inst_id.strip():
            raise ValidationError("目标腿必须给出 inst_id")
        if leg.inst_id in seen:
            raise ValidationError(f"目标组合里 inst_id 重复:{leg.inst_id}")
        seen.add(leg.inst_id)
        if leg.direction not in DIRECTIONS:
            raise ValidationError(f"目标腿方向必须是 long / short, 实际 {leg.direction!r}")
        if not isinstance(leg.target_weight, Decimal) or not leg.target_weight.is_finite():
            raise ValidationError(f"目标权重必须是有限 Decimal, 实际 {leg.target_weight!r}")
        if leg.target_weight < ZERO:
            raise ValidationError(f"目标权重不能为负, 实际 {leg.target_weight}")
        computed += leg.target_weight if leg.direction == SIDE_LONG else -leg.target_weight
    if computed != target.net_exposure:
        raise ValidationError(
            f"目标组合的 net_exposure 必须由各腿推导: {computed} != {target.net_exposure}"
        )


def _adjustment(row: PortfolioAdjustmentRow) -> AdjustmentRecord:
    return AdjustmentRecord(
        adjustment_id=row.adjustment_id,
        instance_id=row.instance_id,
        status=row.status,
        requested_by=row.requested_by,
        requested_at=row.requested_at,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        note=row.decision_note or row.note,
        target=_target_from_json(row.target_json),
    )


# ------------------------------------------------------------------ 杂项


def _require_actor(value: str, field: str) -> str:
    actor = value.strip() if isinstance(value, str) else ""
    if not actor:
        raise ValidationError(f"{field}不能为空")
    if len(actor) > 128:
        raise ValidationError(f"{field}最长 128 个字符")
    return actor


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if len(text) > 512:
        raise ValidationError("说明最长 512 个字符")
    return text or None


def _now() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)

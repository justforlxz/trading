"""持仓域编排：OKX 只读快照同步、手动持仓账本与价格计算。

三件事分开：

- `sync_account` 只调用 OKX 只读 REST，把同一次采集的账户快照与持仓快照写进库；
- `account_summary` / `exchange_positions` 只读库，不联网，也不返回假数字；
- 手动持仓的当前数量与成本只在事务内更新，流水只追加，读流水时按发生时刻重放。

行情价格只从已落库的 K 线取，来源按 `PRICE_SOURCES` 的优先级选择；没有行情时
`price`、`market_value`、`unrealized_pnl` 均为 `None`，并标记
`price_status="unavailable"`，不拿相似标的价格替代。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import (
    Clock,
    Conflict,
    SystemClock,
    UnprocessableEntity,
    ValidationError,
)
from app.db import session_scope
from app.exchange import create_trade_port
from app.instrument import Instrument, display_symbol, get_instrument
from app.market import latest_candle
from app.positions.manual import LONG, SHORT, LedgerTrade, apply_trade, replay_trades
from app.positions.model import (
    DEFAULT_ACCOUNT_ID,
    DEFAULT_CURRENCY,
    AccountSnapshotRow,
    ExchangePositionSnapshotRow,
    ManualPositionRow,
    ManualTradeRow,
)

__all__ = [
    "PRICE_SOURCES",
    "AccountSyncView",
    "AccountView",
    "ExchangePositionView",
    "ExchangePositionsView",
    "ManualPositionView",
    "ManualTradeView",
    "account_summary",
    "add_manual_trade",
    "create_manual_position",
    "delete_manual_position",
    "exchange_positions",
    "list_manual_positions",
    "list_manual_trades",
    "sync_account",
    "update_manual_position",
]

SOURCE_REST = "okx_rest"
STATUS_OK = "ok"
STATUS_STALE = "stale"
STATUS_UNCONFIGURED = "unconfigured"
STATUS_OPEN = "open"
STATUS_CLOSED = "closed"

#: 手动持仓的行情来源优先级；同一标的只用第一个有数据的来源。
PRICE_SOURCES: tuple[str, ...] = ("okx", "okx_spot", "okx_swap", "us_equity_proxy")

BEIJING = ZoneInfo("Asia/Shanghai")
#: 日初基准快照的识别窗口：每日任务在 00:00 触发，允许几分钟的调度抖动。
_BASELINE_WINDOW = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class AccountView:
    """账户卡的只读视图；没有快照时数值字段全部为 `None`。"""

    status: str
    account_id: str
    currency: str
    equity: Decimal | None
    available_equity: Decimal | None
    cash_balance: Decimal | None
    unrealized_pnl: Decimal | None
    used_margin: Decimal | None
    available_margin: Decimal | None
    margin_usage_pct: Decimal | None
    day_pnl: Decimal | None
    captured_at: datetime | None
    source: str | None


@dataclass(frozen=True, slots=True)
class AccountSyncView:
    """一次同步的结果：账户视图 + 写入的持仓条数。"""

    summary: AccountView
    positions_synced: int


@dataclass(frozen=True, slots=True)
class ExchangePositionView:
    """交易所持仓快照 + 标的元数据。"""

    pos_id: str
    inst_id: str
    display_symbol: str
    name: str
    asset_class: str
    pos_side: str
    size: Decimal
    avg_px: Decimal
    mark_px: Decimal | None
    upl: Decimal | None
    upl_ratio: Decimal | None
    lever: Decimal | None
    mgn_mode: str | None
    liq_px: Decimal | None
    margin: Decimal | None


@dataclass(frozen=True, slots=True)
class ExchangePositionsView:
    """最近一次同步的交易所持仓；`as_of` 与该次账户快照相同。"""

    as_of: datetime | None
    status: str
    items: tuple[ExchangePositionView, ...]


@dataclass(frozen=True, slots=True)
class ManualPositionView:
    """手动持仓 + 最新价格与盈亏。"""

    id: str
    inst_id: str
    display_symbol: str
    name: str
    asset_class: str
    side: str
    quantity: Decimal
    avg_cost: Decimal
    stop_px: Decimal | None
    leverage: Decimal | None
    status: str
    note: str | None
    price: Decimal | None
    price_status: str
    price_source: str | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ManualTradeView:
    """一条手动流水及其发生后的持仓状态。"""

    id: str
    position_id: str
    action: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    realized_pnl: Decimal | None
    position_quantity_after: Decimal
    position_avg_cost_after: Decimal
    position_status_after: str
    occurred_at: datetime
    note: str | None
    created_at: datetime


# --------------------------------------------------------------------- 账户


def account_summary(*, clock: Clock | None = None) -> AccountView:
    """最近一条账户快照；状态取当前凭证配置，旧快照不冒充可刷新的数据。"""

    now = (clock or SystemClock()).now()
    with session_scope() as session:
        latest = _latest_account_row(session)
        if latest is None:
            return _empty_account(_unconfigured_status())
        day_pnl = _day_pnl(session, latest, now)
        return _account_view(latest, day_pnl=day_pnl, status=_configured_status())


def sync_account(*, clock: Clock | None = None) -> AccountSyncView:
    """采集一次 OKX 只读快照并落库；上游失败时不写任何半套数据。"""

    if not _credentials_configured():
        return AccountSyncView(_empty_account(STATUS_UNCONFIGURED), 0)

    moment = (clock or SystemClock()).now()
    port = create_trade_port(clock=clock)
    try:
        snapshot = port.account_snapshot()
        positions = port.position_snapshots()
    finally:
        port.close()

    payload_ref = _payload_digest(snapshot)
    with session_scope() as session:
        session.execute(
            postgresql_insert(AccountSnapshotRow)
            .values(
                account_id=DEFAULT_ACCOUNT_ID,
                currency=snapshot.currency,
                equity=snapshot.equity,
                available_equity=snapshot.available_equity,
                cash_balance=snapshot.cash_balance,
                unrealized_pnl=snapshot.unrealized_pnl,
                used_margin=snapshot.used_margin,
                available_margin=snapshot.available_margin,
                margin_ratio=snapshot.margin_ratio,
                captured_at=moment,
                source=SOURCE_REST,
                raw_payload_ref=payload_ref,
            )
            .on_conflict_do_nothing(index_elements=["account_id", "captured_at", "source"])
        )
        if positions:
            session.execute(
                postgresql_insert(ExchangePositionSnapshotRow)
                .values(
                    [
                        {
                            "account_id": DEFAULT_ACCOUNT_ID,
                            "pos_id": item.pos_id,
                            "inst_id": item.inst_id,
                            "pos_side": item.pos_side,
                            "size": item.size,
                            "avg_px": item.avg_px,
                            "mark_px": item.mark_px,
                            "upl": item.upl,
                            "upl_ratio": item.upl_ratio,
                            "lever": item.lever,
                            "mgn_mode": item.mgn_mode,
                            "liq_px": item.liq_px,
                            "margin": item.margin,
                            "captured_at": moment,
                            "source": SOURCE_REST,
                        }
                        for item in positions
                    ]
                )
                .on_conflict_do_nothing(index_elements=["account_id", "pos_id", "captured_at"])
            )
        latest = _latest_account_row(session)
        assert latest is not None  # 刚写入或在同一时刻已存在
        summary = _account_view(
            latest,
            day_pnl=_day_pnl(session, latest, moment),
            status=_configured_status(),
        )
    return AccountSyncView(summary, len(positions))


def exchange_positions() -> ExchangePositionsView:
    """最近一次账户快照同一时刻的交易所持仓；不联网，状态取当前凭证配置。"""

    with session_scope() as session:
        latest = _latest_account_row(session)
        if latest is None:
            return ExchangePositionsView(None, _unconfigured_status(), ())
        rows = list(
            session.scalars(
                select(ExchangePositionSnapshotRow)
                .where(ExchangePositionSnapshotRow.captured_at == latest.captured_at)
                .order_by(ExchangePositionSnapshotRow.pos_id)
            )
        )
    items = tuple(_exchange_position_view(row) for row in rows)
    return ExchangePositionsView(latest.captured_at, _configured_status(), items)


def _latest_account_row(session: Session) -> AccountSnapshotRow | None:
    return session.scalars(
        select(AccountSnapshotRow)
        .order_by(AccountSnapshotRow.captured_at.desc(), AccountSnapshotRow.id.desc())
        .limit(1)
    ).first()


def _day_pnl(
    session: Session,
    latest: AccountSnapshotRow,
    now: datetime,
) -> Decimal | None:
    """今日盈亏：只与北京时间当天 00:00 的基准快照比较。

    没有基准快照就返回 `None`，不能把「上一次同步到这一次同步」的权益差冒充今日
    盈亏。`day_pnl_basis` 在接口上固定为 `equity_only`（未识别入金/出金）。
    """

    local_midnight = now.astimezone(BEIJING).replace(hour=0, minute=0, second=0, microsecond=0)
    start = local_midnight.astimezone(UTC)
    baseline = session.scalars(
        select(AccountSnapshotRow)
        .where(
            AccountSnapshotRow.captured_at >= start,
            AccountSnapshotRow.captured_at < start + _BASELINE_WINDOW,
        )
        .order_by(AccountSnapshotRow.captured_at)
        .limit(1)
    ).first()
    if baseline is None:
        return None
    return latest.equity - baseline.equity


def _account_view(
    row: AccountSnapshotRow,
    *,
    day_pnl: Decimal | None,
    status: str,
) -> AccountView:
    return AccountView(
        status=status,
        account_id=row.account_id,
        currency=row.currency,
        equity=row.equity,
        available_equity=row.available_equity,
        cash_balance=row.cash_balance,
        unrealized_pnl=row.unrealized_pnl,
        used_margin=row.used_margin,
        available_margin=row.available_margin,
        margin_usage_pct=row.margin_ratio * 100,
        day_pnl=day_pnl,
        captured_at=row.captured_at,
        source=row.source,
    )


def _empty_account(status: str) -> AccountView:
    return AccountView(
        status=status,
        account_id=DEFAULT_ACCOUNT_ID,
        currency=DEFAULT_CURRENCY,
        equity=None,
        available_equity=None,
        cash_balance=None,
        unrealized_pnl=None,
        used_margin=None,
        available_margin=None,
        margin_usage_pct=None,
        day_pnl=None,
        captured_at=None,
        source=None,
    )


def _unconfigured_status() -> str:
    return STATUS_STALE if _credentials_configured() else STATUS_UNCONFIGURED


def _configured_status() -> str:
    """当前凭证配置决定状态：有快照但凭据已撤销时，数据可以展示但不能刷新。"""

    return STATUS_OK if _credentials_configured() else STATUS_UNCONFIGURED


def _credentials_configured() -> bool:
    settings = get_settings()
    return all(
        value.strip()
        for value in (settings.okx_api_key, settings.okx_secret_key, settings.okx_passphrase)
    )


def _payload_digest(snapshot: object) -> str:
    """账户快照的摘要哈希：只保留可核对的事实，不保存上游原始应答。"""

    text = "|".join(
        str(value)
        for value in (
            snapshot.currency,  # type: ignore[attr-defined]
            snapshot.equity,  # type: ignore[attr-defined]
            snapshot.available_equity,  # type: ignore[attr-defined]
            snapshot.cash_balance,  # type: ignore[attr-defined]
            snapshot.unrealized_pnl,  # type: ignore[attr-defined]
            snapshot.used_margin,  # type: ignore[attr-defined]
            snapshot.available_margin,  # type: ignore[attr-defined]
            snapshot.margin_ratio,  # type: ignore[attr-defined]
        )
    )
    return hashlib.sha256(text.encode()).hexdigest()


def _exchange_position_view(row: ExchangePositionSnapshotRow) -> ExchangePositionView:
    instrument = get_instrument(row.inst_id)
    return ExchangePositionView(
        pos_id=row.pos_id,
        inst_id=row.inst_id,
        display_symbol=_display_symbol(instrument, row.inst_id),
        name=_name(instrument, row.inst_id),
        asset_class=_asset_class(instrument),
        pos_side=row.pos_side,
        size=row.size,
        avg_px=row.avg_px,
        mark_px=row.mark_px,
        upl=row.upl,
        upl_ratio=row.upl_ratio,
        lever=row.lever,
        mgn_mode=row.mgn_mode,
        liq_px=row.liq_px,
        margin=row.margin,
    )


# ------------------------------------------------------------------- 手动持仓


def list_manual_positions() -> list[ManualPositionView]:
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(ManualPositionRow).order_by(
                    ManualPositionRow.created_at.desc(), ManualPositionRow.id
                )
            )
        )
    return [_manual_position_view(row) for row in rows]


def create_manual_position(
    *,
    inst_id: str,
    side: str,
    quantity: Decimal,
    avg_cost: Decimal,
    stop_px: Decimal | None,
    leverage: Decimal | None,
    note: str | None,
    idempotency_key: str,
    clock: Clock | None = None,
) -> ManualPositionView:
    """创建手动持仓并写入一条 `open` 流水；同一个幂等键返回原持仓。"""

    _require_instrument(inst_id)
    _require_side(side)
    _require_positive(quantity, "数量")
    _require_positive(avg_cost, "平均成本")
    _require_optional_positive(stop_px, "止损价")
    _require_optional_positive(leverage, "杠杆")
    _require_note(note)
    _require_key(idempotency_key)

    moment = (clock or SystemClock()).now()
    try:
        with session_scope() as session:
            existing = _open_position_for_key(session, idempotency_key)
            if existing is not None:
                return existing

            position_id = str(uuid4())
            position = ManualPositionRow(
                id=position_id,
                inst_id=inst_id,
                side=side,
                quantity=quantity,
                avg_cost=avg_cost,
                stop_px=stop_px,
                leverage=leverage,
                status=STATUS_OPEN,
                note=note,
                created_at=moment,
                updated_at=moment,
            )
            session.add(position)
            session.flush()
            session.add(
                ManualTradeRow(
                    id=str(uuid4()),
                    position_id=position_id,
                    action="open",
                    quantity=quantity,
                    price=avg_cost,
                    fee=Decimal(0),
                    occurred_at=moment,
                    note=note,
                    idempotency_key=idempotency_key,
                    created_at=moment,
                )
            )
            session.flush()
        return _manual_position_view(position)
    except IntegrityError:
        # 并发同键：先提交的一方占用唯一键，落败的事务已整体回滚；重查原记录返回。
        with session_scope() as session:
            existing = _open_position_for_key(session, idempotency_key)
        if existing is None:
            raise
        return existing


def _open_position_for_key(session: Session, idempotency_key: str) -> ManualPositionView | None:
    """按幂等键找创建流水的原持仓；键被其他动作占用时按冲突处理。"""

    existing = session.scalar(
        select(ManualTradeRow).where(ManualTradeRow.idempotency_key == idempotency_key)
    )
    if existing is None:
        return None
    if existing.action != "open":
        raise Conflict("幂等键已用于其他手动流水")
    position = session.get(ManualPositionRow, existing.position_id)
    if position is None:
        raise Conflict("幂等键对应的手动持仓不存在")
    return _manual_position_view(position)


def update_manual_position(
    position_id: str,
    *,
    changes: Mapping[str, object],
    clock: Clock | None = None,
) -> ManualPositionView | None:
    """只改止损价、杠杆与备注；数量和成本只能通过流水改变。"""

    allowed = {"stop_px", "leverage", "note"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValidationError(f"不允许修改字段: {', '.join(sorted(unknown))}")
    if "stop_px" in changes:
        _require_optional_positive(changes["stop_px"], "止损价")
    if "leverage" in changes:
        _require_optional_positive(changes["leverage"], "杠杆")
    if "note" in changes:
        _require_note(changes["note"])

    moment = (clock or SystemClock()).now()
    with session_scope() as session:
        position = session.get(ManualPositionRow, position_id)
        if position is None:
            return None
        if "stop_px" in changes:
            position.stop_px = changes["stop_px"]  # type: ignore[assignment]
        if "leverage" in changes:
            position.leverage = changes["leverage"]  # type: ignore[assignment]
        if "note" in changes:
            position.note = changes["note"]  # type: ignore[assignment]
        position.updated_at = moment
        session.flush()
    return _manual_position_view(position)


def add_manual_trade(
    position_id: str,
    *,
    action: str,
    quantity: Decimal,
    price: Decimal,
    fee: Decimal,
    occurred_at: datetime,
    note: str | None,
    idempotency_key: str,
    clock: Clock | None = None,
) -> ManualTradeView | None:
    """写入手动流水并在同一事务内更新持仓；重复幂等键返回原流水。"""

    _require_note(note)
    _require_key(idempotency_key)
    if occurred_at.tzinfo is None:
        raise ValidationError("成交时刻必须带时区")

    moment = (clock or SystemClock()).now()
    with session_scope() as session:
        position = session.scalar(
            select(ManualPositionRow).where(ManualPositionRow.id == position_id).with_for_update()
        )
        if position is None:
            return None

        existing = session.scalar(
            select(ManualTradeRow).where(ManualTradeRow.idempotency_key == idempotency_key)
        )
        if existing is not None:
            if existing.position_id != position_id:
                raise Conflict("幂等键已用于其他手动持仓的流水")
            return _replay_one(session, position_id, existing.id)

        if position.status == STATUS_CLOSED:
            raise Conflict("已平仓的手动持仓不能再写流水")
        last_occurred = session.scalar(
            select(func.max(ManualTradeRow.occurred_at)).where(
                ManualTradeRow.position_id == position_id
            )
        )
        if last_occurred is not None and occurred_at < last_occurred:
            raise UnprocessableEntity(
                f"成交时刻 {occurred_at.isoformat()} 早于该持仓最近的流水 "
                f"{last_occurred.isoformat()}"
            )

        effect = apply_trade(
            action=action,
            side=position.side,
            current_quantity=position.quantity,
            current_avg_cost=position.avg_cost,
            quantity=quantity,
            price=price,
            fee=fee,
        )
        trade = ManualTradeRow(
            id=str(uuid4()),
            position_id=position_id,
            action=action,
            quantity=quantity,
            price=price,
            fee=fee,
            occurred_at=occurred_at,
            note=note,
            idempotency_key=idempotency_key,
            created_at=moment,
        )
        position.quantity = effect.quantity
        position.avg_cost = effect.avg_cost
        position.status = effect.status
        position.updated_at = moment
        session.add(trade)
        session.flush()
        return _manual_trade_view(
            trade,
            quantity_after=effect.quantity,
            avg_cost_after=effect.avg_cost,
            status_after=effect.status,
            realized_pnl=effect.realized_pnl,
        )


def list_manual_trades(position_id: str) -> list[ManualTradeView] | None:
    """按发生时刻倒序返回流水，并带上每条流水之后的持仓数量与成本。"""

    with session_scope() as session:
        position = session.get(ManualPositionRow, position_id)
        if position is None:
            return None
        rows = list(
            session.scalars(select(ManualTradeRow).where(ManualTradeRow.position_id == position_id))
        )
    projections = replay_trades([_ledger_trade(row) for row in rows], side=position.side)
    by_id = {row.id: row for row in rows}
    views = [
        _manual_trade_view(
            by_id[projection.trade.trade_id],
            quantity_after=projection.quantity_after,
            avg_cost_after=projection.avg_cost_after,
            status_after=projection.status_after,
            realized_pnl=projection.realized_pnl,
        )
        for projection in projections
    ]
    views.sort(key=lambda row: (row.occurred_at, row.created_at), reverse=True)
    return views


def delete_manual_position(position_id: str) -> bool | None:
    """删除没有任何流水的手动持仓；已有流水返回 `Conflict`。"""

    with session_scope() as session:
        position = session.get(ManualPositionRow, position_id)
        if position is None:
            return None
        trades = session.scalar(
            select(func.count())
            .select_from(ManualTradeRow)
            .where(ManualTradeRow.position_id == position_id)
        )
        if trades:
            raise Conflict("该手动持仓已有流水, 不能删除")
        session.delete(position)
    return True


def _replay_one(
    session: Session,
    position_id: str,
    trade_id: str,
) -> ManualTradeView:
    position = session.get(ManualPositionRow, position_id)
    if position is None:
        raise Conflict("幂等键对应的手动持仓不存在")
    rows = list(
        session.scalars(select(ManualTradeRow).where(ManualTradeRow.position_id == position_id))
    )
    projections = replay_trades([_ledger_trade(row) for row in rows], side=position.side)
    for projection in projections:
        if projection.trade.trade_id == trade_id:
            row = next(item for item in rows if item.id == trade_id)
            return _manual_trade_view(
                row,
                quantity_after=projection.quantity_after,
                avg_cost_after=projection.avg_cost_after,
                status_after=projection.status_after,
                realized_pnl=projection.realized_pnl,
            )
    raise Conflict("幂等键对应的流水不在该持仓的账本里")


def _manual_position_view(row: ManualPositionRow) -> ManualPositionView:
    instrument = get_instrument(row.inst_id)
    price, source = _latest_price(row.inst_id)
    market_value: Decimal | None = None
    unrealized: Decimal | None = None
    if price is not None:
        market_value = price * row.quantity
        if row.side == LONG:
            unrealized = (price - row.avg_cost) * row.quantity
        else:
            unrealized = (row.avg_cost - price) * row.quantity
    return ManualPositionView(
        id=row.id,
        inst_id=row.inst_id,
        display_symbol=_display_symbol(instrument, row.inst_id),
        name=_name(instrument, row.inst_id),
        asset_class=_asset_class(instrument),
        side=row.side,
        quantity=row.quantity,
        avg_cost=row.avg_cost,
        stop_px=row.stop_px,
        leverage=row.leverage,
        status=row.status,
        note=row.note,
        price=price,
        price_status="ok" if price is not None else "unavailable",
        price_source=source,
        market_value=market_value,
        unrealized_pnl=unrealized,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _manual_trade_view(
    row: ManualTradeRow,
    *,
    quantity_after: Decimal,
    avg_cost_after: Decimal,
    status_after: str,
    realized_pnl: Decimal | None,
) -> ManualTradeView:
    return ManualTradeView(
        id=row.id,
        position_id=row.position_id,
        action=row.action,
        quantity=row.quantity,
        price=row.price,
        fee=row.fee,
        realized_pnl=realized_pnl,
        position_quantity_after=quantity_after,
        position_avg_cost_after=avg_cost_after,
        position_status_after=status_after,
        occurred_at=row.occurred_at,
        note=row.note,
        created_at=row.created_at,
    )


def _ledger_trade(row: ManualTradeRow) -> LedgerTrade:
    return LedgerTrade(
        trade_id=row.id,
        action=row.action,
        quantity=row.quantity,
        price=row.price,
        fee=row.fee,
        occurred_at=row.occurred_at,
        created_at=row.created_at,
    )


def _latest_price(inst_id: str) -> tuple[Decimal | None, str | None]:
    for source in PRICE_SOURCES:
        candle = latest_candle(inst_id, source=source)
        if candle is not None:
            return candle.close, candle.source
    return None, None


def _display_symbol(instrument: Instrument | None, inst_id: str) -> str:
    return inst_id if instrument is None else display_symbol(instrument)


def _name(instrument: Instrument | None, inst_id: str) -> str:
    """标的表没有独立名称字段；产品键是最接近的可读名。"""

    return inst_id if instrument is None else instrument.product_key


def _asset_class(instrument: Instrument | None) -> str:
    return "unknown" if instrument is None else instrument.asset_type


def _require_instrument(inst_id: str) -> Instrument:
    row = get_instrument(inst_id)
    if row is None:
        raise ValidationError(f"标的 {inst_id} 不在标的表里, 先同步标的")
    return row


def _require_side(side: str) -> None:
    if side not in {LONG, SHORT}:
        raise ValidationError(f"持仓方向必须是 long 或 short, 实际 {side!r}")


def _require_positive(value: Decimal, label: str) -> None:
    if value <= 0:
        raise ValidationError(f"{label}必须大于 0")


def _require_optional_positive(value: object, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, Decimal):
        raise ValidationError(f"{label}必须是十进制数")
    _require_positive(value, label)


def _require_note(note: str | None) -> None:
    if note is not None and len(note) > 512:
        raise ValidationError("备注最多 512 个字符")


def _require_key(key: str) -> None:
    if not key.strip():
        raise ValidationError("幂等键不能为空")
    if len(key) > 128:
        raise ValidationError("幂等键最多 128 个字符")

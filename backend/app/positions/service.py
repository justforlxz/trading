"""持仓域编排：OKX 只读快照同步、手动持仓账本与价格计算。

三件事分开：

- `sync_account` 只调用 OKX 只读 REST，把同一次采集的账户快照与持仓快照写进库；
- `account_summary` / `exchange_positions` 只读库，不联网，也不返回假数字；
- 手动持仓的当前数量与成本只在事务内更新，流水只追加，读流水时按发生时刻重放。

行情价格优先从已落库的 K 线取，来源按 `PRICE_SOURCES` 的优先级选择；K 线只覆盖订阅
与自选的标的，长尾持仓可能一行都没有，因此**现货**还有一条兜底：一个来源都查不到时
直接读一次 OKX 公共 ticker。两个来源都带上来源与报价时刻，页面据此说明价格有多旧。
没有行情时 `price`、`market_value`、`unrealized_pnl` 均为 `None`，并标记
`price_status="unavailable"`，不拿相似标的价格替代。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activity import record_activity
from app.config import get_settings
from app.core import (
    AccountSnapshot,
    Clock,
    Conflict,
    DataUnavailable,
    ExchangePosition,
    OrderRecord,
    StopOrder,
    SystemClock,
    TradePort,
    UnprocessableEntity,
    UpstreamError,
    ValidationError,
)
from app.db import session_scope
from app.exchange import ExchangeError, OkxClient, OkxMarketData, create_trade_port
from app.instrument import (
    Instrument,
    display_symbol,
    get_instrument,
    get_instruments,
    notional_value,
    trading_rules,
)
from app.market import latest_candles_by_source, stale_days
from app.positions.curves import CurvePoint, upl_curves
from app.positions.manual import LONG, SHORT, LedgerTrade, apply_trade, replay_trades
from app.positions.model import (
    DEFAULT_ACCOUNT_ID,
    DEFAULT_CURRENCY,
    AccountSnapshotRow,
    ExchangePositionSnapshotRow,
    ManualPositionRow,
    ManualTradeRow,
)
from app.positions.stops import (
    STOP_CONFIRMED,
    STOP_NONE,
    STOP_UNAVAILABLE,
    StopState,
    resolve_stop_states,
)

__all__ = [
    "DEFAULT_ACCOUNT_ID",
    "PRICE_SOURCES",
    "AccountSyncView",
    "AccountView",
    "ExchangePositionView",
    "ExchangePositionsView",
    "ManualPositionView",
    "ManualTradeView",
    "PositionCard",
    "PositionCardsView",
    "account_summary",
    "add_manual_trade",
    "create_manual_position",
    "delete_manual_position",
    "exchange_position_view_from_snapshot",
    "exchange_positions",
    "held_instruments",
    "instrument_order_history",
    "list_manual_positions",
    "list_manual_trades",
    "list_open_manual_positions",
    "position_cards",
    "record_exchange_snapshot",
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
PRICE_SOURCES: tuple[str, ...] = ("okx", "okx_spot", "okx_swap")

#: 库里一个来源都没有时的兜底来源：OKX 公共 ticker 的最新成交价。
TICKER_SOURCE = "okx_ticker"
#: 兜底报价的超时与重试上限。兜底只是锦上添花，不能让整页跟着等上游 10 秒 × 重试。
TICKER_TIMEOUT_SECONDS = 3.0

_HUNDRED = Decimal(100)
#: 没算过的持仓按「未取到」处理，绝不退化成「未挂止损」。
_UNSET_STOP = StopState(STOP_UNAVAILABLE, None)
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
    position_notional: Decimal | None
    position_notional_at: datetime | None
    # 名义敞口与净敞口是**已知持仓**的合计；`notional_status="partial"` 表示还有
    # 持仓没有行情，界面必须在数字前标 `≥`，不能把已知部分当成全部。
    gross_notional: Decimal | None
    net_notional: Decimal | None
    notional_status: str
    # 已用保证金按 `Σ(名义 ÷ 杠杆)` 折算，不读 OKX 的 `used_margin`。
    margin_used: Decimal | None
    margin_usage_floor: bool
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
    #: 止损触发价与三态；`unavailable` 表示这次没取到，不是「没挂」。
    stop_px: Decimal | None
    stop_status: str


@dataclass(frozen=True, slots=True)
class ExchangePositionsView:
    """最近一次同步的交易所持仓；`as_of` 与该次账户快照相同。"""

    as_of: datetime | None
    status: str
    items: tuple[ExchangePositionView, ...]


@dataclass(frozen=True, slots=True)
class PositionCard:
    """持仓卡片：一张卡需要的全部事实，盈亏与占比都由后端算好。

    `upl_curve` 是该持仓的未实现盈亏序列（来自 `exchange_position_snapshots.upl`），
    不是价格 K 线。`stop_status` 三态见 `app.positions.stops`。
    """

    pos_id: str
    inst_id: str
    display_symbol: str
    name: str
    asset_class: str
    #: 标的类别（`SPOT` / `SWAP`）：卡片据此标出「现货 / 永续」，同一标的的两种形态
    #: 才不会显示成同一个名字。标的没同步时为 `None`，界面不猜形态。
    inst_type: str | None
    pos_side: str
    size: Decimal
    avg_px: Decimal
    mark_px: Decimal | None
    #: 标记价的来源与报价时刻（见 `_Quote`）：页面据此说明这个价格有多旧。
    mark_px_source: str | None
    mark_px_at: datetime | None
    #: 标记价是否已经过期，以及过期了几天。过期的价格只是**最后一次已知价**，页面必须
    #: 显式标出，不能和实时价并列展示；没过期时 `mark_px_age_days` 为 `None`。
    mark_px_stale: bool
    mark_px_age_days: int | None
    upl: Decimal | None
    upl_ratio: Decimal | None
    lever: Decimal | None
    mgn_mode: str | None
    liq_px: Decimal | None
    margin: Decimal | None
    notional: Decimal | None
    weight_pct: Decimal | None
    stop_status: str
    #: 该类别有没有止损概念：现货没有止损，界面要留空而不是显示「未取到」。
    stop_supported: bool
    stop_px: Decimal | None
    stop_distance_pct: Decimal | None
    upl_curve: tuple[CurvePoint, ...]


@dataclass(frozen=True, slots=True)
class PositionCardsView:
    """持仓卡片列表；`as_of` 与这次用的持仓快照同刻。

    `hidden_dust_count` 是被展示层隐藏的尘埃条数（名义价值低于阈值）：快照里一行
    都没删，界面据此说明「已隐藏 N 条」。
    """

    as_of: datetime | None
    status: str
    items: tuple[PositionCard, ...]
    hidden_dust_count: int = 0


@dataclass(frozen=True, slots=True)
class _PositionTotals:
    """一次遍历算出的名义合计。

    `notional_exact` 与 `margin_exact` 分开：名义只要求有价格与合约规格，保证金还要求
    知道杠杆。现货持仓没有杠杆，名义算得出来而保证金算不出来，混成一个标志会让
    `position_notional` 平白变成 `None`。
    """

    gross: Decimal
    net: Decimal
    margin: Decimal
    notional_exact: bool
    margin_exact: bool


@dataclass(frozen=True, slots=True)
class _Quote:
    """一个标的的取价结果：价格、来源与报价时刻，三者缺一不可。

    `at` 是价格真正成立的时刻：K 线取收盘时刻，实时报价取上游报价时间。卡片据此
    说明价格有多旧，不把上一周的收盘价说成当前价。
    """

    price: Decimal
    source: str
    at: datetime


@dataclass(frozen=True, slots=True)
class _CardFacts:
    """一张持仓卡片补齐标记价后的事实；占比要等尘埃过滤完的合计才能算。"""

    mark_px: Decimal | None
    #: 标记价的来源与时刻：交易所随持仓下发的、K 线的、或兜底实时报价的。
    mark_px_source: str | None
    mark_px_at: datetime | None
    #: 过期判定与天数：由价格时刻与本次请求时刻相减得到，不在前端口算。
    mark_px_stale: bool
    mark_px_age_days: int | None
    upl: Decimal | None
    upl_ratio: Decimal | None
    notional: Decimal | None
    stop_supported: bool


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


def account_summary(
    *,
    clock: Clock | None = None,
    include_position_notional: bool = True,
) -> AccountView:
    """最近一条账户快照；状态取当前凭证配置，旧快照不冒充可刷新的数据。"""

    now = (clock or SystemClock()).now()
    with session_scope() as session:
        latest = _latest_account_row(session)
        if latest is None:
            return _empty_account(_unconfigured_status())
        day_pnl = _day_pnl(session, latest, now)
        totals = _position_totals(session, latest) if include_position_notional else None
        return _account_view(
            latest,
            day_pnl=day_pnl,
            totals=totals,
            status=_configured_status(),
        )


def sync_account(*, clock: Clock | None = None) -> AccountSyncView:
    """采集一次 OKX 只读快照并落库；上游失败或标的未同步时不写任何半套数据。"""

    if not _credentials_configured():
        return AccountSyncView(_empty_account(STATUS_UNCONFIGURED), 0)

    moment = (clock or SystemClock()).now()
    port = create_trade_port(clock=clock)
    try:
        try:
            snapshot = port.account_snapshot()
            positions = port.position_snapshots()
        except Exception as exc:
            record_activity(
                event_type="account.sync.failed",
                object_type="account",
                object_id=DEFAULT_ACCOUNT_ID,
                summary="账户与持仓同步失败",
                payload={"error_type": type(exc).__name__},
                clock=clock,
            )
            raise
        stop_orders, stops_available = _read_stop_orders(port, clock=clock)
    finally:
        port.close()

    with session_scope() as session:
        _ensure_instruments_synced(session, {item.inst_id for item in positions})

    summary = record_exchange_snapshot(
        captured_at=moment,
        source=SOURCE_REST,
        snapshot=snapshot,
        positions=positions,
        stops=stop_orders,
        stops_available=stops_available,
    )
    assert summary is not None  # 刚刚写入或同一时刻已存在
    record_activity(
        event_type="account.sync.succeeded",
        object_type="account",
        object_id=DEFAULT_ACCOUNT_ID,
        summary=f"账户与持仓同步成功，共 {len(positions)} 条持仓",
        payload={"positions_synced": len(positions)},
        clock=clock,
    )
    return AccountSyncView(summary, len(positions))


def record_exchange_snapshot(
    *,
    captured_at: datetime,
    source: str,
    snapshot: AccountSnapshot | None = None,
    positions: Sequence[ExchangePosition] | None = None,
    stops: Sequence[StopOrder] | None = None,
    stops_available: bool = True,
) -> AccountView | None:
    """把一次账户与持仓快照写进 B2 的表；只写传入的部分，不补造缺失数据。

    `positions` 为空集合表示这一批明确没有持仓，会删除该时刻的旧行并标记该时刻
    已携带持仓批次；传 `None` 表示这次调用不涉及持仓，标记保持原值。传非空集合时
    按 `(account_id, pos_id, captured_at)` 更新，并删除该时刻不在集合里的旧行，
    保证同一时刻的账户与持仓是同一批状态。私有频道推送与 REST 同步共用本函数，
    保证两边落库字段一致。返回账户视图，没有账户快照时返回 `None`。

    `stops` 传 `None` 表示这次不涉及止损（私有频道推送就没有止损），已有行的止损
    列保持原值；传集合时按 `stops_available` 决定是「确认过」还是「没取到」。
    """

    with session_scope() as session:
        if snapshot is not None:
            payload_ref = _payload_digest(snapshot)
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
                    positions_included=positions is not None,
                    captured_at=captured_at,
                    source=source,
                    raw_payload_ref=payload_ref,
                )
                .on_conflict_do_nothing(index_elements=["account_id", "captured_at", "source"])
            )
        if positions is not None:
            # `stops is None`：这次调用（私有频道推送）不涉及止损，止损列一律不写。
            # 不在插入里出现就没有值可覆盖，`ON CONFLICT DO UPDATE` 的 set 里也不包含
            # 它们，于是同一 `(account_id, pos_id, captured_at)` 上 REST 同步写下的
            # 「有止损 / 确认无止损」不会被推送抹成「未取到」。
            stop_states = (
                resolve_stop_states(positions, stops or (), available=stops_available)
                if stops is not None
                else None
            )
            if positions:
                rows = []
                for item in positions:
                    row: dict[str, object] = {
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
                        "captured_at": captured_at,
                        "source": source,
                    }
                    if stop_states is not None:
                        state = stop_states.get(item.pos_id, _UNSET_STOP)
                        row["stop_px"] = state.px
                        row["stop_status"] = state.status
                    rows.append(row)
                insert_positions = postgresql_insert(ExchangePositionSnapshotRow).values(rows)
                updates: dict[str, object] = {
                    "inst_id": insert_positions.excluded.inst_id,
                    "pos_side": insert_positions.excluded.pos_side,
                    "size": insert_positions.excluded.size,
                    "avg_px": insert_positions.excluded.avg_px,
                    "mark_px": insert_positions.excluded.mark_px,
                    "upl": insert_positions.excluded.upl,
                    "upl_ratio": insert_positions.excluded.upl_ratio,
                    "lever": insert_positions.excluded.lever,
                    "mgn_mode": insert_positions.excluded.mgn_mode,
                    "liq_px": insert_positions.excluded.liq_px,
                    "margin": insert_positions.excluded.margin,
                    "source": insert_positions.excluded.source,
                }
                if stop_states is not None:
                    updates["stop_px"] = insert_positions.excluded.stop_px
                    updates["stop_status"] = insert_positions.excluded.stop_status
                session.execute(
                    insert_positions.on_conflict_do_update(
                        index_elements=["account_id", "pos_id", "captured_at"],
                        set_=updates,
                    )
                )
            stale = delete(ExchangePositionSnapshotRow).where(
                ExchangePositionSnapshotRow.account_id == DEFAULT_ACCOUNT_ID,
                ExchangePositionSnapshotRow.captured_at == captured_at,
            )
            if positions:
                stale = stale.where(
                    ExchangePositionSnapshotRow.pos_id.notin_([item.pos_id for item in positions])
                )
            session.execute(stale)
            # 同一时刻可能先写入账户行、后补持仓批次；已有账户行统一标记为已携带。
            session.execute(
                update(AccountSnapshotRow)
                .where(
                    AccountSnapshotRow.account_id == DEFAULT_ACCOUNT_ID,
                    AccountSnapshotRow.captured_at == captured_at,
                )
                .values(positions_included=True)
            )
        if snapshot is None:
            return None
        latest = _latest_account_row(session)
        assert latest is not None  # 刚写入或在同一时刻已存在
        return _account_view(
            latest,
            day_pnl=_day_pnl(session, latest, captured_at),
            totals=_position_totals(session, latest),
            status=_configured_status(),
        )


def exchange_position_view_from_snapshot(item: ExchangePosition) -> ExchangePositionView:
    """推送用的持仓视图：与 `GET /api/positions/exchange` 的条目字段一致。

    私有频道推送不携带止损信息，因此这里如实标成「未取到」；风险层读的是库里的
    快照（`exchange_positions()`），不使用本函数，所以推送不会影响止损判定。
    """

    instrument = get_instrument(item.inst_id)
    return ExchangePositionView(
        pos_id=item.pos_id,
        inst_id=item.inst_id,
        display_symbol=_display_symbol(instrument, item.inst_id),
        name=_name(instrument, item.inst_id),
        asset_class=_asset_class(instrument),
        pos_side=item.pos_side,
        size=item.size,
        avg_px=item.avg_px,
        mark_px=item.mark_px,
        upl=item.upl,
        upl_ratio=item.upl_ratio,
        lever=item.lever,
        mgn_mode=item.mgn_mode,
        liq_px=item.liq_px,
        margin=item.margin,
        stop_px=None,
        stop_status=STOP_UNAVAILABLE,
    )


def _ensure_instruments_synced(session: Session, symbols: set[str]) -> None:
    """持仓或同步结果里的标的必须已经在标的表里，否则拒绝继续。"""

    if not symbols:
        return
    known = set(session.scalars(select(Instrument.symbol).where(Instrument.symbol.in_(symbols))))
    missing = sorted(symbols - known)
    if missing:
        raise DataUnavailable(f"标的 {missing[0]} 不在标的表里, 先同步标的")


def held_instruments() -> tuple[str, ...]:
    """最近一次账户快照里仍有持仓的标的标识，按 `inst_id` 固定顺序；没有快照时为空。

    只回答「哪些标的的行情还在被人用」，不取行情、不算盈亏：K 线刷新拿它拼出要维持
    新鲜的标的集合（见 `app.jobs.candle_refresh`）。持仓行原样返回，不区分现货与永续，
    也不按名义价值过滤——尘埃同样要有一个价格才知道自己是不是尘埃。
    """

    with session_scope() as session:
        latest = _latest_account_row(session)
        if latest is None:
            return ()
        return tuple(
            session.scalars(
                select(ExchangePositionSnapshotRow.inst_id)
                .where(ExchangePositionSnapshotRow.captured_at == latest.captured_at)
                .distinct()
                .order_by(ExchangePositionSnapshotRow.inst_id)
            )
        )


def exchange_positions(*, require_mapped: bool = False) -> ExchangePositionsView:
    """最近一次账户快照同一时刻的交易所持仓；不联网，状态取当前凭证配置。

    默认容忍标的表里找不到的持仓，用原始 `inst_id` 显示，方便提醒、合并视图等
    普通读取继续工作；只有需要保证产品信息完整的调用方显式开启 `require_mapped`。
    """

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
        stops = _stop_answers(session, [row.pos_id for row in rows])
        if require_mapped:
            _ensure_instruments_synced(session, {row.inst_id for row in rows})
    # 标的元数据一次取完：持仓行数再多也不按行发语句。
    instruments = get_instruments(row.inst_id for row in rows)
    items = tuple(
        _exchange_position_view(row, instruments.get(row.inst_id), stops.get(row.pos_id, NO_STOP))
        for row in rows
    )
    return ExchangePositionsView(latest.captured_at, _configured_status(), items)


def position_cards(
    range_key: str = "1d",
    *,
    clock: Clock | None = None,
) -> PositionCardsView:
    """持仓卡片：按未实现盈亏绝对值降序，带每条持仓的盈亏曲线与止损三态。

    排序放在后端：前端再排一次就会出现「同一份数据两种顺序」，也不符合「前端不重算」
    的约束。没有行情的持仓照样出卡片——`mark_px` / `upl` 为空，界面用骨架占位补位，
    整卡消失比空值更难察觉。

    现货持仓没有上游标记价：先用该标的最近一根已收盘 K 线的收盘价补，库里一个来源都
    查不到时再读一次 OKX 公共 ticker 兜底（见 `_quotes`）。

    K 线会停更（按需同步只在用户点开标的时触发），因此每张卡都要回答「这个价过期了
    没有」：价格时刻距 `clock` 超过 `PRICE_MAX_AGE` 就标成过期并给出天数，页面据此
    把最后一次已知价和实时价分开说。
    尘埃（名义价值低于 `POSITION_DUST_NOTIONAL`）只在卡片列表里隐藏，快照行原样保留
    给对账；隐藏条数经 `hidden_dust_count` 交给界面说明，占比分母也取可见部分，因此
    可见卡片的 `weight_pct` 合计仍是 100%。
    """

    with session_scope() as session:
        latest = _latest_account_row(session)
        if latest is None:
            return PositionCardsView(None, _unconfigured_status(), ())
        rows = list(
            session.scalars(
                select(ExchangePositionSnapshotRow)
                .where(ExchangePositionSnapshotRow.captured_at == latest.captured_at)
                .order_by(ExchangePositionSnapshotRow.pos_id)
            )
        )
        stops = _stop_answers(session, [row.pos_id for row in rows])
        status = _configured_status()

    moment = (clock or SystemClock()).now()
    instruments = get_instruments(row.inst_id for row in rows)
    # 一批取回所有标的的最新价：按行查会退化成 N 条语句，而持仓页一次就有十几行。
    quotes = _quotes(rows, instruments)
    curves = upl_curves(range_key)
    threshold = _dust_threshold()
    facts = {
        row.pos_id: _card_facts(
            row,
            instruments.get(row.inst_id),
            quotes.get(row.inst_id),
            latest.captured_at,
            moment,
        )
        for row in rows
    }
    visible = [row for row in rows if not _is_dust(facts[row.pos_id].notional, threshold)]
    gross = sum(
        (facts[row.pos_id].notional or Decimal(0) for row in visible),
        Decimal(0),
    )
    cards = []
    for row in visible:
        fact = facts[row.pos_id]
        instrument = instruments.get(row.inst_id)
        stop = stops.get(row.pos_id, NO_STOP)
        cards.append(
            PositionCard(
                pos_id=row.pos_id,
                inst_id=row.inst_id,
                display_symbol=_display_symbol(instrument, row.inst_id),
                name=_name(instrument, row.inst_id),
                asset_class=_asset_class(instrument),
                inst_type=None if instrument is None else instrument.inst_type,
                pos_side=row.pos_side,
                size=row.size,
                avg_px=row.avg_px,
                mark_px=fact.mark_px,
                mark_px_source=fact.mark_px_source,
                mark_px_at=fact.mark_px_at,
                mark_px_stale=fact.mark_px_stale,
                mark_px_age_days=fact.mark_px_age_days,
                upl=fact.upl,
                upl_ratio=fact.upl_ratio,
                lever=row.lever,
                mgn_mode=row.mgn_mode,
                liq_px=row.liq_px,
                margin=row.margin,
                notional=fact.notional,
                weight_pct=_weight_pct(fact.notional, gross),
                stop_status=stop.status,
                stop_supported=fact.stop_supported,
                stop_px=stop.px,
                stop_distance_pct=_stop_distance_pct(fact.mark_px, stop.px, row.pos_side),
                upl_curve=curves.get(row.pos_id, ()),
            )
        )
    cards.sort(
        key=lambda card: (-abs(card.upl if card.upl is not None else Decimal(0)), card.pos_id)
    )
    return PositionCardsView(
        latest.captured_at,
        status,
        tuple(cards),
        hidden_dust_count=len(rows) - len(cards),
    )


def instrument_order_history(
    inst_id: str,
    *,
    clock: Clock | None = None,
) -> tuple[OrderRecord, ...]:
    """单个标的的挂单与历史订单，按时间倒序。

    订单历史只在 OKX 侧保留（近 7 天在 `orders-history`，更早在
    `orders-history-archive`），没有对应的本地表可以读；本模块另一处读侧联网是
    `_missing_quotes()` 的兜底报价，两者都只在库里没有对应事实时才发请求。上游失败抛
    `ExchangeError`，接口层据此回 502，不返回空列表冒充「没有订单」。
    """

    if not _credentials_configured():
        raise DataUnavailable("未配置 OKX 密钥，无法读取订单历史")
    port = create_trade_port(clock=clock)
    try:
        return tuple(port.order_history(inst_id))
    finally:
        port.close()


def _card_facts(
    row: ExchangePositionSnapshotRow,
    instrument: Instrument | None,
    quote: _Quote | None,
    captured_at: datetime,
    now: datetime,
) -> _CardFacts:
    """一张卡片在算占比之前的原始事实：补齐标记价后的价格、盈亏与名义价值。

    标记价与名义价值的来源不同，必须分开取：

    - 标记价只在**现货**缺价时用最近价补。永续的标记价由交易所给，拿别的价格
      冒充会与强平价、保证金口径分叉，宁可留空。
    - 名义价值的兜底对所有类别都生效（与账户卡的 `_position_totals` 同一口径）：
      名义价值只要求「有一个价格」，标记价缺失不影响它算得出来。

    标记价的来源与时刻跟着价格一起返回：交易所随持仓下发的按快照时刻算，K 线与实时
    报价各带自己的时刻，页面才不会把上周的收盘价当成当前价。

    过期判定只看价格时刻，不看来源：K 线停更与上游报价本身变旧是同一件事，都表现为
    「这个价的时刻很久以前」。过期的价格只降级成「最后一次已知价」，不删、也不换成
    别的数字。
    """

    mark_px = row.mark_px
    mark_px_at = captured_at if mark_px is not None else None
    mark_px_source = row.source if mark_px is not None else None
    if mark_px is None and _is_spot_position(instrument) and quote is not None:
        mark_px = quote.price
        mark_px_source = quote.source
        mark_px_at = quote.at
    fallback = None if quote is None else quote.price
    upl, upl_ratio = _spot_pnl(row, instrument, mark_px)
    age_days = None if mark_px_at is None else stale_days(mark_px_at, now)
    return _CardFacts(
        mark_px=mark_px,
        mark_px_source=mark_px_source,
        mark_px_at=mark_px_at,
        mark_px_stale=age_days is not None,
        mark_px_age_days=age_days,
        upl=upl,
        upl_ratio=upl_ratio,
        notional=_notional(
            row.size, row.mark_px if row.mark_px is not None else fallback, instrument
        ),
        stop_supported=_stop_supported(instrument),
    )


def _is_spot_position(instrument: Instrument | None) -> bool:
    """该标的的持仓是不是由余额推导（现货）；标的没同步时不猜。"""

    return instrument is not None and not trading_rules(instrument.inst_type).has_position_endpoint


def _spot_pnl(
    row: ExchangePositionSnapshotRow,
    instrument: Instrument | None,
    mark_px: Decimal | None,
) -> tuple[Decimal | None, Decimal | None]:
    """现货的未实现盈亏与盈亏率：只有成本价已知时才按 `(标记价 − 成本价) × 数量` 算。

    余额行的 `upl` 一律不用：上游对现货余额记的 0 表示「没有持仓成本」，不是「不亏
    不赚」，直接显示 0.00 会被读成一个结论。成本价未知时两者都留空，界面写「未提供」，
    也不拿标记价当成本价——那算出来的是整个名义价值，不是盈亏。
    """

    if not _is_spot_position(instrument):
        return row.upl, row.upl_ratio
    if mark_px is None or row.avg_px <= 0:
        return None, None
    upl = (mark_px - row.avg_px) * row.size
    cost = row.avg_px * abs(row.size)
    return upl, None if cost == 0 else upl / cost


def _stop_supported(instrument: Instrument | None) -> bool:
    """该类别有没有止损概念。

    止损委托只在有持仓接口的类别上存在（现货没有）。标的没同步时不猜，按「有」
    处理——界面显示「未取到」，而不是断言「现货无止损」。
    """

    if instrument is None:
        return True
    return trading_rules(instrument.inst_type).has_position_endpoint


def _dust_threshold() -> Decimal:
    """尘埃阈值：名义价值低于它的持仓不进卡片列表。"""

    return Decimal(str(get_settings().position_dust_notional))


def _is_dust(notional: Decimal | None, threshold: Decimal) -> bool:
    """算不出名义价值的行不算尘埃：不能拿「没有价格」断言它「不到 1 USDT」。"""

    return notional is not None and notional < threshold


def _notional(
    size: Decimal,
    price: Decimal | None,
    instrument: Instrument | None,
) -> Decimal | None:
    """一条交易所持仓的名义价值；缺价格或规格时返回 `None`。"""

    if instrument is None or price is None:
        return None
    return notional_value(
        size=size,
        price=price,
        qty_unit=trading_rules(instrument.inst_type).qty_unit,
        ct_val=instrument.ct_val,
        ct_mult=instrument.ct_mult,
    )


def _weight_pct(notional: Decimal | None, gross: Decimal) -> Decimal | None:
    """占比 = 本条名义 ÷ 已知名义合计；分母为 0 时不给值。"""

    if notional is None or gross <= 0:
        return None
    return notional / gross * _HUNDRED


def _effective_lever(lever: Decimal | None) -> Decimal:
    """保证金折算用的杠杆：没有杠杆就按 1 倍算。

    现货是全额买入，占用的资金就是名义本身（`名义 ÷ 1`）。把「没有杠杆」当成「杠杆
    未知」而跳过，会让现货持仓的保证金贡献恒为 0——实测一条 152.77 名义的现货持仓
    把账户占用率从 45% 压到 12%，用户会以为账户很轻。
    """

    if lever is None or lever <= 0:
        return Decimal(1)
    return lever


def _stop_distance_pct(
    mark_px: Decimal | None,
    stop_px: Decimal | None,
    pos_side: str,
) -> Decimal | None:
    """标记价到止损价的距离百分比：多单看下方、空单看上方，正数表示还有缓冲。"""

    if mark_px is None or stop_px is None or mark_px == 0:
        return None
    diff = mark_px - stop_px if pos_side != SHORT else stop_px - mark_px
    return diff / mark_px * _HUNDRED


def _read_stop_orders(
    port: TradePort,
    *,
    clock: Clock | None,
) -> tuple[list[StopOrder], bool]:
    """取止损委托；失败只降级为「未取到」，不影响账户与持仓的同步。

    止损查询失败时把它记成一条活动事件，然后继续写账户与持仓：一次止损失败不该
    让整次同步失败，但也不能悄悄变成「没有止损」。
    """

    try:
        return list(port.stop_orders()), True
    except Exception as exc:
        record_activity(
            event_type="account.sync.stops_unavailable",
            object_type="account",
            object_id=DEFAULT_ACCOUNT_ID,
            summary="止损委托读取失败，本次按「未取到」处理",
            payload={"error_type": type(exc).__name__},
            clock=clock,
        )
        return [], False


def _latest_account_row(session: Session) -> AccountSnapshotRow | None:
    return session.scalars(
        select(AccountSnapshotRow)
        .order_by(AccountSnapshotRow.captured_at.desc(), AccountSnapshotRow.id.desc())
        .limit(1)
    ).first()


@dataclass(frozen=True, slots=True)
class _StopAnswer:
    """一条持仓的止损结论：三态之一，外加 `confirmed` 时的触发价。"""

    status: str
    px: Decimal | None


#: 库里没有任何一条带止损结论的行时的回答：问都没问过，不能说成「没有止损」。
NO_STOP = _StopAnswer(STOP_UNAVAILABLE, None)


def _stop_answers(session: Session, pos_ids: Sequence[str]) -> dict[str, _StopAnswer]:
    """`pos_id` → 最近一条带止损结论的快照行。

    不能读「最新一行」：私有频道推送每 5 秒写一条快照，按设计不携带止损列，最新一条
    几乎总是它。止损结论只在 REST 同步（每 5 分钟一次）写下的行里，因此按 `pos_id` 取
    最近一条 `confirmed` / `none` 的行。没有任何结论的 `pos_id` 不出现在结果里，由调用
    方回落 `NO_STOP`——「从没问过」与「问过、没有」必须分开。
    """

    if not pos_ids:
        return {}
    rows = session.execute(
        select(
            ExchangePositionSnapshotRow.pos_id,
            ExchangePositionSnapshotRow.stop_status,
            ExchangePositionSnapshotRow.stop_px,
        )
        .where(
            ExchangePositionSnapshotRow.account_id == DEFAULT_ACCOUNT_ID,
            ExchangePositionSnapshotRow.pos_id.in_(pos_ids),
            ExchangePositionSnapshotRow.stop_status.in_((STOP_CONFIRMED, STOP_NONE)),
        )
        .distinct(ExchangePositionSnapshotRow.pos_id)
        .order_by(
            ExchangePositionSnapshotRow.pos_id,
            ExchangePositionSnapshotRow.captured_at.desc(),
            ExchangePositionSnapshotRow.id.desc(),
        )
    )
    return {pos_id: _StopAnswer(status, px) for pos_id, status, px in rows}


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


def _position_totals(session: Session, latest: AccountSnapshotRow) -> _PositionTotals:
    """一次遍历算出名义敞口、净敞口与已用保证金。

    口径（本模块是唯一实现，别处不许另立一套）：

    - 名义 = 合约规格折算的价值，缺失价格/规格/标的时这条持仓无法计入；
    - 已用保证金 = `Σ(名义 ÷ 杠杆)`，**不读 OKX 的 `used_margin`**：逐仓模式下上游
      `imr` 返回空、`used_margin` 恒为 0，用它会得出「保证金占用 0%」的假结论；
    - 任何一条持仓无法计入时 `exact=False`，界面据此在数字前标 `≥`。

    最新账户快照没有携带持仓批次且该时刻没有持仓行时，名义合计退回 0 并标
    `exact=False`——「不知道有没有持仓」不能当成「没有持仓」。
    """

    exchange_rows = list(
        session.scalars(
            select(ExchangePositionSnapshotRow).where(
                ExchangePositionSnapshotRow.captured_at == latest.captured_at
            )
        )
    )
    if not exchange_rows and not latest.positions_included:
        return _PositionTotals(Decimal(0), Decimal(0), Decimal(0), False, False)

    symbols = {row.inst_id for row in exchange_rows}
    instruments = (
        {
            row.symbol: row
            for row in session.scalars(select(Instrument).where(Instrument.symbol.in_(symbols)))
        }
        if symbols
        else {}
    )

    notional_exact = True
    margin_exact = True
    long_notional = Decimal(0)
    short_notional = Decimal(0)
    margin = Decimal(0)
    for row in exchange_rows:
        instrument = instruments.get(row.inst_id)
        if instrument is None:
            notional_exact = False
            margin_exact = False
            continue
        price = row.mark_px
        if price is None:
            price = _latest_price(row.inst_id)
        value = notional_value(
            size=row.size,
            price=price,
            qty_unit=trading_rules(instrument.inst_type).qty_unit,
            ct_val=instrument.ct_val,
            ct_mult=instrument.ct_mult,
        )
        if value is None:
            notional_exact = False
            margin_exact = False
            continue
        if row.pos_side == "short":
            short_notional += value
        else:
            long_notional += value
        margin += value / _effective_lever(row.lever)

    manual_rows = session.scalars(
        select(ManualPositionRow).where(ManualPositionRow.status == STATUS_OPEN)
    )
    for row in manual_rows:
        price = _latest_price(row.inst_id)
        value = notional_value(size=row.quantity, price=price, qty_unit="base")
        if value is None:
            notional_exact = False
            margin_exact = False
            continue
        if row.side == SHORT:
            short_notional += value
        else:
            long_notional += value
        margin += value / _effective_lever(row.leverage)

    return _PositionTotals(
        gross=long_notional + short_notional,
        net=long_notional - short_notional,
        margin=margin,
        notional_exact=notional_exact,
        margin_exact=margin_exact,
    )


def _account_view(
    row: AccountSnapshotRow,
    *,
    day_pnl: Decimal | None,
    totals: _PositionTotals | None,
    status: str,
) -> AccountView:
    """账户卡的只读视图。

    `margin_usage_pct` 用 `Σ(名义 ÷ 杠杆) ÷ 权益` 重算，不使用快照里的 `margin_ratio`
    （逐仓模式下上游给的是 0）。`margin_used` 同理；`used_margin` 保留上游原值，
    只作为历史数据被其他页面读取，不参与本页的计算。
    """

    margin_used = totals.margin if totals is not None else None
    margin_usage_pct = (
        margin_used / row.equity * _HUNDRED if margin_used is not None and row.equity != 0 else None
    )
    notional_exact = totals is not None and totals.notional_exact
    margin_exact = totals is not None and totals.margin_exact
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
        margin_usage_pct=margin_usage_pct,
        day_pnl=day_pnl,
        position_notional=totals.gross if notional_exact else None,
        position_notional_at=row.captured_at if notional_exact else None,
        gross_notional=totals.gross if totals is not None else None,
        net_notional=totals.net if totals is not None else None,
        notional_status="exact" if notional_exact else "partial",
        margin_used=margin_used,
        margin_usage_floor=not margin_exact,
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
        position_notional=None,
        position_notional_at=None,
        gross_notional=None,
        net_notional=None,
        notional_status="partial",
        margin_used=None,
        margin_usage_floor=True,
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


def _exchange_position_view(
    row: ExchangePositionSnapshotRow,
    instrument: Instrument | None,
    stop: _StopAnswer,
) -> ExchangePositionView:
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
        stop_px=stop.px,
        stop_status=stop.status,
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
    return _manual_position_views(rows)


def list_open_manual_positions() -> tuple[ManualPositionView, ...]:
    """仍在持仓状态的手动持仓；与 `list_manual_positions` 同一次读法，只是先筛状态。"""

    return tuple(item for item in list_manual_positions() if item.status == STATUS_OPEN)


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
            record_activity(
                session=session,
                event_type="position.manual.created",
                object_type="manual_position",
                object_id=position_id,
                summary=f"创建手动持仓 {inst_id} {side} {quantity}",
                payload={"inst_id": inst_id, "side": side, "quantity": str(quantity)},
                clock=clock,
            )
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
        record_activity(
            session=session,
            event_type="position.manual.updated",
            object_type="manual_position",
            object_id=position_id,
            summary=f"更新手动持仓 {position.inst_id} 的{'、'.join(sorted(changes))}",
            payload={"inst_id": position.inst_id, "fields": sorted(changes)},
            clock=clock,
        )
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
        record_activity(
            session=session,
            event_type="position.manual.trade_added",
            object_type="manual_position",
            object_id=position_id,
            summary=f"手动持仓 {position.inst_id} 写入{action}流水",
            payload={
                "inst_id": position.inst_id,
                "action": action,
                "quantity": str(quantity),
                "price": str(price),
            },
            clock=clock,
        )
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
        inst_id = position.inst_id
        session.delete(position)
        record_activity(
            session=session,
            event_type="position.manual.deleted",
            object_type="manual_position",
            object_id=position_id,
            summary=f"删除手动持仓 {inst_id}",
            payload={"inst_id": inst_id},
        )
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


def _manual_position_views(rows: Sequence[ManualPositionRow]) -> list[ManualPositionView]:
    """一批手动持仓共用两次读取：标的元数据一次、各来源的最新价一次。"""

    if not rows:
        return []
    symbols = [row.inst_id for row in rows]
    instruments = get_instruments(symbols)
    prices = _latest_prices(symbols)
    return [
        _manual_position_row(row, instruments.get(row.inst_id), prices[row.inst_id]) for row in rows
    ]


def _manual_position_view(row: ManualPositionRow) -> ManualPositionView:
    """单条手动持仓的视图；批量路径走 `_manual_position_views` 共用取数。"""

    return _manual_position_views([row])[0]


def _manual_position_row(
    row: ManualPositionRow,
    instrument: Instrument | None,
    quote: _Quote | None,
) -> ManualPositionView:
    last_price = None if quote is None else quote.price
    market_value: Decimal | None = None
    unrealized: Decimal | None = None
    if last_price is not None:
        market_value = last_price * row.quantity
        if row.side == LONG:
            unrealized = (last_price - row.avg_cost) * row.quantity
        else:
            unrealized = (row.avg_cost - last_price) * row.quantity
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
        price=last_price,
        price_status="ok" if last_price is not None else "unavailable",
        price_source=None if quote is None else quote.source,
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


def _latest_price(inst_id: str) -> Decimal | None:
    """单条标的最新可信价；按批读的路径走 `_latest_prices`。"""

    quote = _latest_prices([inst_id])[inst_id]
    return None if quote is None else quote.price


def _latest_prices(inst_ids: Sequence[str]) -> dict[str, _Quote | None]:
    """一批标的最新可信价：按 `PRICE_SOURCES` 顺序取第一个有数据的来源。

    `at` 取那根 K 线的**收盘时刻**：日线的开盘与收盘差一个周期，卡片据此说明价格有多
    旧，不把上一周的收盘价当成当前价。
    """

    latest = latest_candles_by_source(inst_ids, sources=PRICE_SOURCES)
    prices: dict[str, _Quote | None] = {}
    for inst_id in dict.fromkeys(inst_ids):
        prices[inst_id] = None
        for source in PRICE_SOURCES:
            candle = latest.get((inst_id, source))
            if candle is not None:
                prices[inst_id] = _Quote(
                    price=candle.close,
                    source=candle.source,
                    at=candle.open_time + timedelta(seconds=candle.timeframe.seconds),
                )
                break
    return prices


def _quotes(
    rows: Sequence[ExchangePositionSnapshotRow],
    instruments: Mapping[str, Instrument],
) -> dict[str, _Quote | None]:
    """持仓卡片用的价格：先查库，缺价的**现货**再读一次实时报价兜底。"""

    prices = _latest_prices([row.inst_id for row in rows])
    prices.update(_missing_quotes(rows, instruments, prices))
    return prices


def _missing_quotes(
    rows: Sequence[ExchangePositionSnapshotRow],
    instruments: Mapping[str, Instrument],
    prices: Mapping[str, _Quote | None],
) -> dict[str, _Quote]:
    """库里一个来源都没有的现货标的：直接读一次 OKX 公共 ticker。

    K 线只覆盖订阅与自选的标的，长尾持仓可能一行都没有；没有价就没有名义价值、占比，
    也算不出它是不是尘埃。这条兜底只补**现货**：永续的标记价由交易所随持仓下发，
    不在这里猜。取不到就整批放弃，卡片留空——兜底价不值得让页面等上游，也不编价格。
    """

    missing = [
        inst_id
        for inst_id, instrument in ((row.inst_id, instruments.get(row.inst_id)) for row in rows)
        if _is_spot_position(instrument) and prices.get(inst_id) is None
    ]
    if not missing:
        return {}
    quotes: dict[str, _Quote] = {}
    settings = get_settings().model_copy(
        update={"okx_http_timeout_seconds": TICKER_TIMEOUT_SECONDS, "okx_http_max_retries": 0}
    )
    try:
        with OkxClient(settings=settings) as client:
            market = OkxMarketData(client)
            for inst_id in dict.fromkeys(missing):
                try:
                    ticker = market.ticker_quote(inst_id)
                except ExchangeError:
                    # 这只标的没有报价不该拖垮整页；下一只照试。
                    continue
                quotes[inst_id] = _Quote(ticker.last, TICKER_SOURCE, ticker.ts)
    except (ExchangeError, UpstreamError):
        # 连接层面的失败：后面的标的必然一样失败，直接放弃这一批。
        return quotes
    return quotes


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

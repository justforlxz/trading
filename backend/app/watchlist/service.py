"""自选域：分组、条目、价格提醒，以及基于已落库日线的行情快照。

行情口径（本域唯一出处）：取该标的已落库的 **日线**，`last_price` 是最新一根
收盘价，`change_pct_24h` 是它与前一根收盘价的涨跌幅，`volume_24h_quote` 是
`最新收盘价 × 最新成交量`。库里的成交量是基础币种的成交量，没有单独的报价
成交量列，所以这里按收盘价折算成近似成交额，口径写在响应字段之外，不做伪
装。日线不足两根时明确报缺数据（`DataUnavailable`），不补造历史。

提醒只存规则：触发时间留给后续节点的任务回填，本域不主动扫描行情。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import DataUnavailable, InvariantViolation, ValidationError
from app.db import session_scope
from app.instrument import Instrument
from app.market import correlation, load_candles
from app.watchlist.model import PriceAlertRow, WatchlistGroup, WatchlistItemRow

__all__ = [
    "DEFAULT_GROUP",
    "QUOTE_BAR",
    "AlertSnapshot",
    "Quote",
    "RelatedCandidate",
    "WatchlistEntry",
    "add_item",
    "clear_alert",
    "list_entries",
    "list_groups",
    "move_item",
    "related_instruments",
    "remove_item",
    "set_alert",
    "tracked_instruments",
]

DEFAULT_GROUP = "默认"
QUOTE_BAR = "1d"

_CHANGE_PLACES = Decimal("0.000001")
_TURNOVER_PLACES = Decimal("0.01")
_CORRELATION_PLACES = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class Quote:
    """自选条目的一次行情快照，三列都来自同一根最新日线。"""

    last_price: Decimal
    change_pct_24h: Decimal
    volume_24h_quote: Decimal


@dataclass(frozen=True, slots=True)
class AlertSnapshot:
    """提醒规则的只读视图，避免调用方拿到 ORM 实例。"""

    inst_id: str
    direction: str
    price: Decimal
    enabled: bool
    triggered_at: datetime | None


@dataclass(frozen=True, slots=True)
class WatchlistEntry:
    """一条自选：标的元数据 + 分组 + 行情快照 + 可选提醒。"""

    instrument: Instrument
    group: str
    added_at: datetime
    quote: Quote
    alert: AlertSnapshot | None


@dataclass(frozen=True, slots=True)
class RelatedCandidate:
    """与目标标的相关的候选，按相关系数绝对值排序后交给上层。"""

    inst_id: str
    product_key: str
    asset_type: str
    correlation: Decimal


def quote(inst_id: str) -> Quote:
    """按已落库日线算行情快照；数据不够两根就报缺数据，不补造。"""

    candles = load_candles(inst_id, QUOTE_BAR)
    if len(candles) < 2:
        raise DataUnavailable(f"标的 {inst_id} 的日线不足 2 根无法计算 24 小时涨跌幅")

    previous, latest = candles[-2], candles[-1]
    if previous.close == 0:
        raise DataUnavailable(f"标的 {inst_id} 的前一根日线收盘价为 0 无法计算涨跌幅")

    change = (latest.close - previous.close) / previous.close * Decimal(100)
    return Quote(
        last_price=latest.close,
        change_pct_24h=change.quantize(_CHANGE_PLACES),
        volume_24h_quote=(latest.close * latest.volume).quantize(_TURNOVER_PLACES),
    )


def list_entries() -> list[WatchlistEntry]:
    """按加入顺序列出全部自选条目；行情缺失直接报错，不静默跳过。"""

    with session_scope() as session:
        rows = list(
            session.scalars(
                select(WatchlistItemRow).order_by(
                    WatchlistItemRow.added_at, WatchlistItemRow.inst_id
                )
            )
        )
        instruments = {row.inst_id: session.get(Instrument, row.inst_id) for row in rows}
        alerts = {row.inst_id: _snapshot(row) for row in session.scalars(select(PriceAlertRow))}

        entries: list[WatchlistEntry] = []
        for row in rows:
            instrument = instruments[row.inst_id]
            if instrument is None:
                raise InvariantViolation(f"自选标的 {row.inst_id} 在标的表里不存在")
            entries.append(
                WatchlistEntry(
                    instrument=instrument,
                    group=row.group_name,
                    added_at=row.added_at,
                    quote=quote(row.inst_id),
                    alert=alerts.get(row.inst_id),
                )
            )
        return entries


def list_groups() -> list[str]:
    """按创建顺序列出分组名。"""

    with session_scope() as session:
        return list(
            session.scalars(
                select(WatchlistGroup.name).order_by(WatchlistGroup.created_at, WatchlistGroup.name)
            )
        )


def tracked_instruments() -> list[Instrument]:
    """自选里跟踪的标的，不取行情、不读提醒；按 `symbol` 固定顺序返回。

    只回答「用户在跟踪哪些标的」，不参与行情计算：入口页的行情快照由
    `list_entries` 负责，这里给分析层（关系网络）一个不依赖 K 线是否齐全的标的集合。
    """

    with session_scope() as session:
        ids = list(
            session.scalars(select(WatchlistItemRow.inst_id).order_by(WatchlistItemRow.inst_id))
        )
        if not ids:
            return []
        return list(
            session.scalars(
                select(Instrument).where(Instrument.symbol.in_(ids)).order_by(Instrument.symbol)
            )
        )


def add_item(inst_id: str, group: str = DEFAULT_GROUP) -> WatchlistEntry | None:
    """把标的加入自选；标的未知返回 `None`，重复加入按入参错误处理。"""

    symbol = inst_id.strip()
    name = group.strip() or DEFAULT_GROUP

    with session_scope() as session:
        instrument = session.get(Instrument, symbol)
        if instrument is None:
            return None
        if session.get(WatchlistItemRow, symbol) is not None:
            raise ValidationError(f"标的 {symbol} 已经在自选里")

        # 先算行情：加进去却读不出最新价，等于留给前端一个会炸的条目。
        entry_quote = quote(symbol)
        added_at = datetime.now(UTC)
        _ensure_group(session, name, added_at)
        session.add(WatchlistItemRow(inst_id=symbol, group_name=name, added_at=added_at))
        return WatchlistEntry(
            instrument=instrument,
            group=name,
            added_at=added_at,
            quote=entry_quote,
            alert=None,
        )


def move_item(inst_id: str, group: str) -> WatchlistEntry | None:
    """把条目换到另一个分组；条目不存在返回 `None`，原分组空了就一并删掉。"""

    symbol = inst_id.strip()
    name = group.strip() or DEFAULT_GROUP

    with session_scope() as session:
        row = session.get(WatchlistItemRow, symbol)
        if row is None:
            return None
        instrument = session.get(Instrument, symbol)
        if instrument is None:
            raise InvariantViolation(f"自选标的 {symbol} 在标的表里不存在")

        entry_quote = quote(symbol)
        previous = row.group_name
        _ensure_group(session, name, datetime.now(UTC))
        row.group_name = name
        _drop_group_if_empty(session, previous)
        return WatchlistEntry(
            instrument=instrument,
            group=name,
            added_at=row.added_at,
            quote=entry_quote,
            alert=_alert_of(session, symbol),
        )


def remove_item(inst_id: str) -> bool:
    """删除条目及其提醒；不存在返回 `False`。"""

    symbol = inst_id.strip()

    with session_scope() as session:
        row = session.get(WatchlistItemRow, symbol)
        if row is None:
            return False

        previous = row.group_name
        alert = session.get(PriceAlertRow, symbol)
        if alert is not None:
            session.delete(alert)
        session.delete(row)
        session.flush()
        _drop_group_if_empty(session, previous)
        return True


def set_alert(
    inst_id: str, direction: str, price: Decimal, *, enabled: bool = True
) -> AlertSnapshot | None:
    """写入或覆盖提醒规则；标的不在自选里返回 `None`。"""

    symbol = inst_id.strip()

    with session_scope() as session:
        if session.get(WatchlistItemRow, symbol) is None:
            return None

        row = session.get(PriceAlertRow, symbol)
        if row is None:
            row = PriceAlertRow(inst_id=symbol, direction=direction, price=price, enabled=enabled)
            session.add(row)
        else:
            row.direction = direction
            row.price = price
            row.enabled = enabled
        # 规则被改写后旧的触发时间不再成立。
        row.triggered_at = None
        return _snapshot(row)


def clear_alert(inst_id: str) -> bool:
    """删除提醒规则；本来就没有返回 `False`。"""

    symbol = inst_id.strip()

    with session_scope() as session:
        row = session.get(PriceAlertRow, symbol)
        if row is None:
            return False
        session.delete(row)
        return True


def related_instruments(inst_id: str, window_days: int) -> list[RelatedCandidate] | None:
    """按窗口内日线相关性给候选排序；标的不存在返回 `None`，自身不参与。

    候选集是标的表里的全部其他标的，相关性样本不足的（没有 K 线）直接丢弃，
    不做插值。当前实现对每个候选单独取一次日线，候选多时是一次全表扫描级别的
    读取，放在后续节点随指标缓存一起优化。
    """

    symbol = inst_id.strip()

    with session_scope() as session:
        if session.get(Instrument, symbol) is None:
            return None
        candidates = [
            (row.symbol, row.product_key, row.asset_type)
            for row in session.scalars(select(Instrument).where(Instrument.symbol != symbol))
        ]

    # K 线时间戳精确到秒，窗口起点也跟着截断到秒。
    start = (datetime.now(UTC) - timedelta(days=window_days)).replace(microsecond=0)
    related: list[RelatedCandidate] = []
    for candidate_id, product_key, asset_type in candidates:
        coefficient = correlation(symbol, candidate_id, QUOTE_BAR, start=start).coefficient
        if coefficient is None:
            continue
        related.append(
            RelatedCandidate(
                inst_id=candidate_id,
                product_key=product_key,
                asset_type=asset_type,
                correlation=Decimal(str(coefficient)).quantize(_CORRELATION_PLACES),
            )
        )

    related.sort(key=lambda item: abs(item.correlation), reverse=True)
    return related


def _ensure_group(session: Session, name: str, created_at: datetime) -> None:
    """分组按需创建：加条目或搬到新分组时自动补登记。"""

    if session.get(WatchlistGroup, name) is None:
        session.add(WatchlistGroup(name=name, created_at=created_at))


def _drop_group_if_empty(session: Session, name: str) -> None:
    """条目搬空或删空后删掉分组，避免列表里留空壳分组。"""

    remaining = session.scalar(
        select(func.count())
        .select_from(WatchlistItemRow)
        .where(WatchlistItemRow.group_name == name)
    )
    if remaining:
        return
    group = session.get(WatchlistGroup, name)
    if group is not None:
        session.delete(group)


def _snapshot(row: PriceAlertRow) -> AlertSnapshot:
    return AlertSnapshot(
        inst_id=row.inst_id,
        direction=row.direction,
        price=row.price,
        enabled=row.enabled,
        triggered_at=row.triggered_at,
    )


def _alert_of(session: Session, inst_id: str) -> AlertSnapshot | None:
    row = session.get(PriceAlertRow, inst_id)
    return None if row is None else _snapshot(row)

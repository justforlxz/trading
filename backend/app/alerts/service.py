"""提醒的落库、去重、状态流转与规则扫描。

扫描只使用已落库、已收盘的日线：`candles` 表本身只收 `confirm=true` 的 K 线。
去重键由「标的 + 规则 + bar + 方向或阈值」组成，数据库唯一约束是最终保证。
条件恢复或同一规则出现新 bar 时，旧提醒标记为 `expired` 并写一条活动，不删除行。

大盘异动（`market`）与组合异动（`watchlist`）不是单标的规则：它们读指数日线、自选整体
与宏观收益率读数，去重键带「方向 + 级别」而不带 bar（详见 `app.alerts.rules`）。这两类
规则的触发时机是行情调度收到新数据之后（`scan_market_alerts`），接口的默认扫描
（`scan_alerts`）也会带上它们，用户打开页面时看到的就是同一份结果。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.activity import queue_event, record_activity
from app.alerts.model import AlertEventRow
from app.alerts.rules import (
    ALERT_SEVERITIES,
    ALERT_STATUSES,
    ALERT_TYPES,
    MARKET_SCAN_RULES,
    SCAN_MANAGED_RULES,
    AlertCandidate,
    data_gap_candidates,
    market_index_candidates,
    price_range_candidates,
    spread_candidates,
    technical_candidates,
    us10y_candidates,
    watchlist_candidates,
)
from app.core import Bar, Clock, Conflict, SystemClock, ValidationError
from app.db import session_scope
from app.instrument import Instrument
from app.macro import GRANULARITY_DAILY, macro_overview
from app.market import MARKET_INDEXES, integrity, load_candles
from app.positions import exchange_positions, list_manual_positions
from app.risk import (
    RULE_HIGH_LEVERAGE,
    RULE_MARGIN_USAGE,
    RULE_SINGLE_INSTRUMENT_WEIGHT,
    RULE_STOP_DISTANCE,
    RULE_STOP_MISSING,
    exposure_report,
)
from app.strategy import list_user_strategies
from app.watchlist import tracked_instruments

__all__ = [
    "AlertRecord",
    "ScanResult",
    "get_alert",
    "list_alerts",
    "record_candidate",
    "scan_alerts",
    "scan_market_alerts",
    "update_alert_status",
]

logger = logging.getLogger(__name__)

MAX_LIMIT = 200
RISK_RULE_VERSION = "b3-exposure-v1"
RISK_BAR = "1d"
_HUNDRED = Decimal(100)
# 技术指标最多回看 60 根日线，180 个自然日足够覆盖并留出停牌与周末的余量。
TECHNICAL_LOOKBACK_DAYS = 180
# 大盘与组合规则要 20 个交易日的 ATR 基线，120 个自然日足够覆盖并留出假日的余量。
MARKET_LOOKBACK_DAYS = 120
_RISK_TITLES = {
    RULE_STOP_MISSING: "持仓缺少止损",
    RULE_STOP_DISTANCE: "止损距离过近",
    RULE_HIGH_LEVERAGE: "杠杆过高",
    RULE_SINGLE_INSTRUMENT_WEIGHT: "单标的占比过高",
    RULE_MARGIN_USAGE: "保证金使用率过高",
}


@dataclass(frozen=True, slots=True)
class AlertRecord:
    """一条提醒的只读视图。"""

    id: str
    type: str
    severity: str
    instrument_id: str | None
    rule_id: str
    rule_version: str | None
    title: str
    detail: str
    payload: Mapping[str, object]
    status: str
    triggered_at: datetime
    expires_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ScanResult:
    """一次扫描的结果：新插入、重新激活各多少条（合并计入 created）与本次过期数。"""

    created: int
    expired: int


def list_alerts(
    *,
    status: str | None = None,
    type: str | None = None,
    severity: str | None = None,
    instrument_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> tuple[tuple[AlertRecord, ...], str | None]:
    """按触发时间倒序列出提醒，返回（本页记录，下一页游标）。"""

    if limit < 1 or limit > MAX_LIMIT:
        raise ValidationError(f"条数上限必须在 1 到 {MAX_LIMIT} 之间: {limit}")
    conditions = []
    if status is not None:
        conditions.append(AlertEventRow.status == _require_status(status))
    if type is not None:
        conditions.append(AlertEventRow.type == _require_type(type))
    if severity is not None:
        conditions.append(AlertEventRow.severity == _require_severity(severity))
    if instrument_id is not None:
        conditions.append(AlertEventRow.instrument_id == instrument_id.strip())
    if cursor:
        triggered_at, row_id = _parse_cursor(cursor)
        conditions.append(
            (AlertEventRow.triggered_at < triggered_at)
            | ((AlertEventRow.triggered_at == triggered_at) & (AlertEventRow.id < row_id))
        )

    statement = (
        select(AlertEventRow)
        .where(*conditions)
        .order_by(AlertEventRow.triggered_at.desc(), AlertEventRow.id.desc())
        .limit(limit + 1)
    )
    with session_scope() as session:
        rows = list(session.scalars(statement))
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit and page:
        last = page[-1]
        next_cursor = f"{last.triggered_at.isoformat()}:{last.id}"
    return tuple(_record(row) for row in page), next_cursor


def get_alert(alert_id: str) -> AlertRecord | None:
    """按标识读取一条提醒；不存在返回 `None`。"""

    with session_scope() as session:
        row = session.get(AlertEventRow, alert_id)
    return None if row is None else _record(row)


def update_alert_status(
    alert_id: str,
    status: str,
    *,
    clock: Clock | None = None,
) -> AlertRecord | None:
    """把待处理提醒改成已确认或已忽略，并写一条活动。"""

    if status not in {"acknowledged", "ignored"}:
        raise ValidationError("提醒状态只能改成 acknowledged 或 ignored")
    moment = (clock or SystemClock()).now()
    with session_scope() as session:
        row = session.get(AlertEventRow, alert_id, with_for_update=True)
        if row is None:
            return None
        if row.status != "pending":
            raise Conflict(f"提醒 {alert_id} 当前状态是 {row.status}, 不能再次处置")
        row.status = status
        row.updated_at = moment
        queue_event(session, "alert.updated", _row_event(row), as_of=moment)
        record_activity(
            session=session,
            event_type=f"alert.{status}",
            object_type="alert",
            object_id=row.id,
            summary=f"提醒「{row.title}」已{'确认' if status == 'acknowledged' else '忽略'}",
            payload={"alert_id": row.id, "rule_id": row.rule_id, "status": status},
            clock=clock,
        )
    return get_alert(alert_id)


def scan_alerts(*, clock: Clock | None = None) -> ScanResult:
    """扫描全部规则（含大盘与组合），写入新提醒并标记已恢复的旧提醒。"""

    moment = _moment(clock)
    return _record_candidates(
        _all_candidates(moment), moment, clock=clock, scope=SCAN_MANAGED_RULES
    )


def scan_market_alerts(*, clock: Clock | None = None) -> ScanResult:
    """只扫大盘异动与组合异动；行情调度收到新的日线后调用它。

    单独一条入口只是为了不把风险、技术这些与行情 tick 无关的规则带进每分钟的调度轮次，
    判定与落库仍走同一个 `_record_candidates`。**判过期的范围必须跟着缩小**：这一轮没有
    评估技术、价格、数据与风险规则，就不能把它们仍在待处理的提醒当成「条件已恢复」。
    """

    moment = _moment(clock)
    return _record_candidates(
        _market_and_watchlist_candidates(moment),
        moment,
        clock=clock,
        scope=MARKET_SCAN_RULES,
    )


def _moment(clock: Clock | None) -> datetime:
    return (clock or SystemClock()).now().astimezone(UTC).replace(microsecond=0)


def _all_candidates(moment: datetime) -> list[AlertCandidate]:
    """一次完整扫描的全部候选；单标的规则先按标的表过滤，指数与组合规则没有标的。"""

    return _drop_unknown_instruments(
        _risk_candidates(moment)
        + _instrument_candidates(moment)
        + _market_and_watchlist_candidates(moment)
    )


def _market_and_watchlist_candidates(moment: datetime) -> list[AlertCandidate]:
    return _market_candidates(moment) + _watchlist_candidates(moment)


def _record_candidates(
    candidates: list[AlertCandidate],
    moment: datetime,
    *,
    clock: Clock | None,
    scope: Collection[str],
) -> ScanResult:
    unique = {candidate.dedup_key: candidate for candidate in candidates}

    created = 0
    expired = 0
    new_groups: set[tuple[str, str, str | None]] = set()
    with session_scope() as session:
        for candidate in unique.values():
            # 并发扫描会同时看到「不存在」并同时插入；唯一约束是最终保证，
            # `ON CONFLICT DO NOTHING` 让后到的请求安静地跳过，而不是抛 500。
            statement = (
                pg_insert(AlertEventRow)
                .values(**_row_values(candidate))
                .on_conflict_do_nothing(index_elements=[AlertEventRow.dedup_key])
                .returning(AlertEventRow.id)
            )
            inserted_id = session.scalar(statement)
            if inserted_id is None:
                # 唯一约束命中：条件恢复后同一天再次成立时，把 expired 行重新
                # 激活为 pending，而不是永远压在 expired 里。
                existing = session.scalar(
                    select(AlertEventRow)
                    .where(AlertEventRow.dedup_key == candidate.dedup_key)
                    .with_for_update()
                )
                if existing is None or existing.status != "expired":
                    continue
                # 重新激活沿用同一 `dedup_key` 的旧行，但严重程度、说明、载荷与
                # 规则版本都要换成本次候选的值，否则页面显示的是上一次触发的数值。
                for field, value in _row_values(candidate).items():
                    if field in {"id", "dedup_key", "created_at"}:
                        continue
                    setattr(existing, field, value)
                existing.updated_at = moment
                queue_event(session, "alert.updated", _row_event(existing), as_of=moment)
                record_activity(
                    session=session,
                    event_type="alert.reopened",
                    object_type="alert",
                    object_id=existing.id,
                    summary=f"提醒「{existing.title}」条件再次成立",
                    payload={
                        "alert_id": existing.id,
                        "rule_id": existing.rule_id,
                        "instrument_id": existing.instrument_id,
                    },
                    clock=clock,
                )
                created += 1
                new_groups.add((existing.type, existing.rule_id, existing.instrument_id))
                continue
            queue_event(
                session, "alert.created", _candidate_event(candidate, inserted_id), as_of=moment
            )
            record_activity(
                session=session,
                event_type="alert.created",
                object_type="alert",
                object_id=inserted_id,
                summary=f"新提醒「{candidate.title}」",
                payload={
                    "alert_id": inserted_id,
                    "type": candidate.type,
                    "rule_id": candidate.rule_id,
                    "instrument_id": candidate.instrument_id,
                },
                clock=clock,
            )
            created += 1
            new_groups.add((candidate.type, candidate.rule_id, candidate.instrument_id))

        expired = _expire_stale(
            session, unique.values(), new_groups, moment, clock=clock, scope=scope
        )
    return ScanResult(created=created, expired=expired)


def record_candidate(candidate: AlertCandidate) -> dict[str, object] | None:
    """把一条候选提醒写成一行，返回推送载荷；同一 `dedup_key` 已存在时返回 `None`。

    与提醒扫描共用同一套落库字段与推送载荷形状（`GET /api/alerts` 的条目），区别只在
    调用方：扫描按周期覆盖全部规则，事件管道只处理刚收到的那根 K 线。唯一约束是唯一
    保证，同一候选并发写入时后到的安静跳过，因此调用方可以按「返回 `None` 就不投递」
    处理，不需要自己判重。

    事件管道不写活动流水，与事件管道的价格偏离提醒一致：提醒行本身就是记录。
    """

    with session_scope() as session:
        statement = (
            pg_insert(AlertEventRow)
            .values(**_row_values(candidate))
            .on_conflict_do_nothing(index_elements=[AlertEventRow.dedup_key])
            .returning(AlertEventRow.id)
        )
        inserted_id = session.scalar(statement)
    if inserted_id is None:
        return None
    return _candidate_event(candidate, inserted_id)


def _drop_unknown_instruments(candidates: list[AlertCandidate]) -> list[AlertCandidate]:
    """标的表里没有的标的无法落成提醒；跳过这些候选，不影响其他提醒。"""

    symbols = {
        candidate.instrument_id for candidate in candidates if candidate.instrument_id is not None
    }
    if not symbols:
        return candidates
    with session_scope() as session:
        known = set(
            session.scalars(select(Instrument.symbol).where(Instrument.symbol.in_(symbols)))
        )
    return [
        candidate
        for candidate in candidates
        if candidate.instrument_id is None or candidate.instrument_id in known
    ]


def _risk_candidates(moment: datetime) -> list[AlertCandidate]:
    exposure = exposure_report(clock=None)
    positions = {item.position_ref: item for item in exposure.positions}
    bar_key = moment.strftime("%Y-%m-%d")
    found: list[AlertCandidate] = []
    for rule in exposure.rules:
        position = positions.get(rule.position_ref or "")
        instrument_id = None if position is None else position.inst_id
        scope = instrument_id or rule.position_ref or "portfolio"
        title = _RISK_TITLES.get(rule.rule_id, rule.rule_id)
        found.append(
            AlertCandidate(
                type="risk",
                severity="critical" if rule.level == "critical" else "warning",
                instrument_id=instrument_id,
                rule_id=rule.rule_id,
                rule_version=RISK_RULE_VERSION,
                title=title,
                detail=_risk_detail(rule.rule_id, rule.value, rule.threshold, scope),
                dedup_key=f"risk|{rule.rule_id}|{scope}|{bar_key}|{_number(rule.threshold)}",
                triggered_at=moment,
                payload={
                    "position_ref": rule.position_ref,
                    "value": None if rule.value is None else str(rule.value),
                    "threshold": None if rule.threshold is None else str(rule.threshold),
                },
            )
        )
    return found


def _market_candidates(moment: datetime) -> list[AlertCandidate]:
    """三个指数的单日涨跌，加上 10Y 收益率与 2Y→10Y 利差的变化。"""

    start = moment - timedelta(days=MARKET_LOOKBACK_DAYS)
    found: list[AlertCandidate] = []
    for index in MARKET_INDEXES:
        bars = _daily_series(index.symbol, start)
        found.extend(market_index_candidates(index, bars, moment=moment))
    found.extend(_rate_candidates(moment))
    return found


def _rate_candidates(moment: datetime) -> list[AlertCandidate]:
    """收益率读数来自宏观域的日线结算值；读失败时跳过，不让它拖垮其他规则。"""

    try:
        overview = macro_overview()
    except Exception:  # 宏观读数读不出来只影响这两条规则
        logger.exception("宏观读数读取失败, 本轮跳过收益率提醒")
        return []
    daily = {
        reading.series_id: reading
        for reading in overview.readings
        if reading.granularity == GRANULARITY_DAILY
    }
    ten = daily.get("us10y")
    if ten is None or ten.value is None or ten.change is None or ten.as_of is None:
        return []
    trading_day = ten.as_of.date()
    found = us10y_candidates(
        change_pp=ten.change, value=ten.value, trading_day=trading_day, moment=moment
    )
    two = daily.get("us2y")
    if two is None or two.value is None or two.change is None or two.as_of is None:
        return found
    if two.as_of.date() != trading_day:
        # 两腿不在同一个结算日：凑出来的差值不是期限利差，宁可这一轮不报。
        return found
    found.extend(
        spread_candidates(
            current_bp=(ten.value - two.value) * _HUNDRED,
            previous_bp=((ten.value - ten.change) - (two.value - two.change)) * _HUNDRED,
            trading_day=trading_day,
            moment=moment,
        )
    )
    return found


def _watchlist_candidates(moment: datetime) -> list[AlertCandidate]:
    """自选整体走弱：只吃有日线的自选标的，没有日线的标的无法判断涨跌。"""

    start = moment - timedelta(days=MARKET_LOOKBACK_DAYS)
    series = {item.symbol: _daily_series(item.symbol, start) for item in tracked_instruments()}
    return watchlist_candidates(
        {symbol: bars for symbol, bars in series.items() if bars}, moment=moment
    )


def _daily_series(symbol: str, start: datetime) -> list[Bar]:
    """某标的的日线序列，只取最新一根所在来源的行。

    换过数据源后旧来源的行还留在 `candles` 里；把两个来源的日线接成一条序列会算出
    根本不存在的跳空，ATR 也跟着失真。因此以最新一根的来源为准。
    """

    bars = load_candles(symbol, RISK_BAR, start=start)
    if not bars:
        return []
    newest = max(bars, key=lambda bar: bar.open_time)
    return [bar for bar in bars if bar.source == newest.source]


def _instrument_candidates(moment: datetime) -> list[AlertCandidate]:
    found: list[AlertCandidate] = []
    start = moment - timedelta(days=TECHNICAL_LOOKBACK_DAYS)
    for symbol in _tracked_symbols():
        bars = load_candles(symbol, RISK_BAR, start=start)
        if not bars:
            continue
        found.extend(technical_candidates(symbol, bars, moment=moment))
        found.extend(price_range_candidates(symbol, bars, moment=moment))
        report = integrity(symbol, RISK_BAR)
        found.extend(data_gap_candidates(symbol, report, moment=moment))
    return found


def _tracked_symbols() -> list[str]:
    symbols = {item.symbol for item in tracked_instruments()}
    symbols.update(item.inst_id for item in exchange_positions().items)
    symbols.update(item.inst_id for item in list_manual_positions() if item.status == "open")
    strategies, _ = list_user_strategies(status="enabled", limit=100)
    for strategy in strategies:
        symbols.update(strategy.instrument_ids)
    return sorted(symbols)


def _expire_stale(
    session: Session,
    candidates: Collection[AlertCandidate],
    new_groups: set[tuple[str, str, str | None]],
    moment: datetime,
    *,
    clock: Clock | None,
    scope: Collection[str],
) -> int:
    """把这一轮**评估过**、且条件已不再成立的提醒标为过期。

    `scope` 是这一轮负责的规则集合：没在里面的规则一个都不能碰——一次只扫大盘的轮次
    没有看技术形态与持仓风险，把它们的待处理提醒判成「已恢复」等于凭空清空用户的提醒。
    """

    current_keys = {candidate.dedup_key for candidate in candidates}
    active_groups = {
        (candidate.type, candidate.rule_id, candidate.instrument_id) for candidate in candidates
    }
    statement = select(AlertEventRow).where(
        AlertEventRow.status.in_(("pending", "acknowledged")),
        AlertEventRow.rule_id.in_(sorted(scope)),
    )
    if current_keys:
        statement = statement.where(AlertEventRow.dedup_key.notin_(current_keys))
    # 行锁让并发扫描串行处理同一批旧提醒，避免同一条恢复记录写两次活动。
    rows = list(session.scalars(statement.order_by(AlertEventRow.id).with_for_update()))
    expired = 0
    for row in rows:
        if row.rule_id not in scope:
            # 防御性兜底：不归这一轮维护的提醒，状态由产出方负责，这里不碰。
            continue
        group = (row.type, row.rule_id, row.instrument_id)
        if group not in new_groups and group in active_groups:
            continue
        if row.expires_at is not None and row.expires_at <= moment:
            continue
        previous = row.status
        row.status = "expired"
        row.expires_at = moment
        row.updated_at = moment
        queue_event(session, "alert.updated", _row_event(row), as_of=moment)
        record_activity(
            session=session,
            event_type="alert.expired",
            object_type="alert",
            object_id=row.id,
            summary=f"提醒「{row.title}」条件已恢复",
            payload={
                "alert_id": row.id,
                "previous_status": previous,
                "rule_id": row.rule_id,
                "instrument_id": row.instrument_id,
            },
            clock=clock,
        )
        expired += 1
    return expired


def _candidate_event(candidate: AlertCandidate, alert_id: str) -> dict[str, object]:
    """新提醒的推送载荷；字段与 `GET /api/alerts` 的条目一致。"""

    return {
        "id": alert_id,
        "type": candidate.type,
        "severity": candidate.severity,
        "instrument_id": candidate.instrument_id,
        "rule_id": candidate.rule_id,
        "rule_version": candidate.rule_version,
        "title": candidate.title,
        "detail": candidate.detail,
        "payload": dict(candidate.payload),
        "status": "pending",
        "triggered_at": candidate.triggered_at.isoformat(),
        "expires_at": candidate.expires_at.isoformat() if candidate.expires_at else None,
    }


def _row_event(row: AlertEventRow) -> dict[str, object]:
    """已落库提醒的推送载荷；字段与 `GET /api/alerts` 的条目一致。"""

    try:
        payload = json.loads(row.payload_json)
    except (TypeError, ValueError):
        payload = {}
    return {
        "id": row.id,
        "type": row.type,
        "severity": row.severity,
        "instrument_id": row.instrument_id,
        "rule_id": row.rule_id,
        "rule_version": row.rule_version,
        "title": row.title,
        "detail": row.detail,
        "payload": payload if isinstance(payload, dict) else {},
        "status": row.status,
        "triggered_at": row.triggered_at.isoformat(),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


def _row_values(candidate: AlertCandidate) -> dict[str, object]:
    return {
        "id": "al_" + uuid4().hex[:24],
        "type": candidate.type,
        "severity": candidate.severity,
        "instrument_id": candidate.instrument_id,
        "rule_id": candidate.rule_id,
        "rule_version": candidate.rule_version,
        "title": candidate.title,
        "detail": candidate.detail,
        "payload_json": json.dumps(
            candidate.payload, ensure_ascii=False, sort_keys=True, default=str
        ),
        "status": "pending",
        "dedup_key": candidate.dedup_key,
        "triggered_at": candidate.triggered_at,
        "expires_at": candidate.expires_at,
        "updated_at": candidate.triggered_at,
    }


def _record(row: AlertEventRow) -> AlertRecord:
    try:
        payload = json.loads(row.payload_json)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"提醒 {row.id} 的 payload 不是合法 JSON") from exc
    return AlertRecord(
        id=row.id,
        type=row.type,
        severity=row.severity,
        instrument_id=row.instrument_id,
        rule_id=row.rule_id,
        rule_version=row.rule_version,
        title=row.title,
        detail=row.detail,
        payload=payload if isinstance(payload, dict) else {},
        status=row.status,
        triggered_at=row.triggered_at,
        expires_at=row.expires_at,
        updated_at=row.updated_at,
    )


def _risk_detail(rule_id: str, value: Decimal | None, threshold: Decimal | None, scope: str) -> str:
    if rule_id == RULE_STOP_MISSING:
        return f"{scope} 没有有效止损记录"
    label = {
        RULE_STOP_DISTANCE: "止损距离",
        RULE_HIGH_LEVERAGE: "杠杆",
        RULE_SINGLE_INSTRUMENT_WEIGHT: "单标的权重",
        RULE_MARGIN_USAGE: "保证金使用率",
    }.get(rule_id, "指标")
    return f"{scope} 的{label} {_number(value)}，阈值 {_number(threshold)}"


def _number(value: Decimal | None) -> str:
    if value is None:
        return "无"
    return format(value.normalize(), "f")


def _require_type(value: str) -> str:
    if value not in ALERT_TYPES:
        raise ValidationError(f"未知提醒类型 {value!r}")
    return value


def _require_severity(value: str) -> str:
    if value not in ALERT_SEVERITIES:
        raise ValidationError(f"未知提醒级别 {value!r}")
    return value


def _require_status(value: str) -> str:
    if value not in ALERT_STATUSES:
        raise ValidationError(f"未知提醒状态 {value!r}")
    return value


def _parse_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        stamp, row_id = cursor.rsplit(":", maxsplit=1)
        return datetime.fromisoformat(stamp), row_id
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"提醒游标不合法: {cursor!r}") from exc

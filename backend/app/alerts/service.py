"""提醒的落库、去重、状态流转与规则扫描。

扫描只使用已落库、已收盘的日线：`candles` 表本身只收 `confirm=true` 的 K 线。
去重键由「标的 + 规则 + bar + 方向或阈值」组成，数据库唯一约束是最终保证。
条件恢复或同一规则出现新 bar 时，旧提醒标记为 `expired` 并写一条活动，不删除行。
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.activity import record_activity
from app.alerts.model import AlertEventRow
from app.alerts.rules import (
    ALERT_SEVERITIES,
    ALERT_STATUSES,
    ALERT_TYPES,
    AlertCandidate,
    data_gap_candidates,
    price_range_candidates,
    technical_candidates,
)
from app.core import Clock, Conflict, SystemClock, ValidationError
from app.db import session_scope
from app.market import integrity, load_candles
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
    "scan_alerts",
    "update_alert_status",
]

MAX_LIMIT = 200
RISK_RULE_VERSION = "b3-exposure-v1"
RISK_BAR = "1d"
# 技术指标最多回看 60 根日线，180 个自然日足够覆盖并留出停牌与周末的余量。
TECHNICAL_LOOKBACK_DAYS = 180
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
    """一次扫描的结果：新插入与本次过期各多少条。"""

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
    """扫描风险、技术、价格与数据规则，写入新提醒并标记已恢复的旧提醒。"""

    moment = (clock or SystemClock()).now().astimezone(UTC).replace(microsecond=0)
    candidates = _risk_candidates(moment) + _instrument_candidates(moment)
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
                continue
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

        expired = _expire_stale(session, unique.values(), new_groups, moment, clock=clock)
    return ScanResult(created=created, expired=expired)


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
) -> int:
    current_keys = {candidate.dedup_key for candidate in candidates}
    active_groups = {
        (candidate.type, candidate.rule_id, candidate.instrument_id) for candidate in candidates
    }
    statement = select(AlertEventRow).where(AlertEventRow.status.in_(("pending", "acknowledged")))
    if current_keys:
        statement = statement.where(AlertEventRow.dedup_key.notin_(current_keys))
    # 行锁让并发扫描串行处理同一批旧提醒，避免同一条恢复记录写两次活动。
    rows = list(session.scalars(statement.order_by(AlertEventRow.id).with_for_update()))
    expired = 0
    for row in rows:
        if row.dedup_key in current_keys:
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

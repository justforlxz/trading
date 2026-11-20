"""规则状态机：价格偏离越过阈值时产出一条 `AlertRaised`，回落后重新布防。

判定只用推送自带的三路价格，不需要 K 线：同一标的的**最新成交价**与**指数价**分别
代表 OKX 自己的成交和跨交易所的参考价，两者偏离过大说明报价已经不可直接参考
（美股永续在休市期间尤其常见）。偏离度直接复用 `app.market.divergence` 的实现与
默认阈值，事件层不重新定义一套公式与取整方式。

状态按 `(标的, 规则)` 记在内存里：
- 首次越过阈值 → 落一条提醒，产出 `state=triggered` 的告警事件并进入「已触发」；
- 仍在阈值外 → 不再产出（连续越过只投递一次）；
- 回落到阈值内 → 把该标的仍待处理的管线提醒改成 `expired`（并写一条活动），产出一条
  `state=cleared` 的事件，下一次越过重新产出。

`cleared` 事件不带提醒内容，通道不会投递它；它的作用是让后面的 `dedupe` 看到状态
真的变了，否则同一条规则在同一个进程里只会被放行一次。提醒本身在回落时同步落成
`expired`，所以待处理列表不会只进不出。

研判只针对 `quote`。其他种类（账户、持仓，以及已经成形的 `alert`）没有研判规则，
原样交给后面的工序，通道要接这类事件不需要改本文件。

进程重启后状态清空，仍在阈值外的标的会在下一笔推送重新产出一次告警；这是有意的：
判断依据只在内存里，重启后没有历史状态可用，宁可多报一次也不假装记得。

告警落库沿用 `alert_events` 已有字段，`dedup_key` 加上了越界时刻，因此同一天再次
越界是另一条记录，而不是被唯一约束吞掉。落库失败时不推进状态，下一笔推送会重试。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.activity import record_activity
from app.alerts import AlertEventRow
from app.core import ValidationError
from app.db import session_scope
from app.events.event import DomainEvent
from app.market import DEFAULT_THRESHOLD_PCT, DivergenceAlert, Quote, divergence

if TYPE_CHECKING:
    from app.events.pipeline import CallNext, Middleware, PipelineDeps

__all__ = ["DEVIATION_THRESHOLD_PCT", "RULE_ID", "middleware"]

logger = logging.getLogger(__name__)

RULE_ID = "price_deviation"
RULE_VERSION = "stream-v1"
ALERT_TYPE = "price"
ALERT_SEVERITY = "warning"
#: 成交价与指数价偏离达到这个比例就值得看一眼；与跨源偏离共用同一个默认值。
DEVIATION_THRESHOLD_PCT = DEFAULT_THRESHOLD_PCT


def middleware(_deps: PipelineDeps) -> Middleware:
    # 每个管线一份状态：`(标的, 规则) -> 当前是否在阈值外`。
    crossed: dict[tuple[str, str], bool] = {}

    async def rule_engine(event: DomainEvent, call_next: CallNext) -> None:
        if event.kind != "quote" or event.inst_id is None:
            await call_next(event)
            return
        decision, cleared = _evaluate(
            event.inst_id, dict(event.payload), crossed, occurred_at=event.occurred_at
        )
        if cleared:
            expired = await asyncio.to_thread(_expire_pending, event.inst_id, event.occurred_at)
            await call_next(
                DomainEvent(
                    kind="alert",
                    inst_id=event.inst_id,
                    payload={"rule_id": RULE_ID, "state": "cleared", "expired": expired},
                    occurred_at=event.occurred_at,
                )
            )
        if decision is None:
            return
        alert = await asyncio.to_thread(_record_alert, decision)
        if alert is None:
            # 落库失败或同一条越界已存在：状态退回未触发，下一笔推送会重试/重判。
            crossed[(decision.inst_id, RULE_ID)] = False
            return
        await call_next(
            DomainEvent(
                kind="alert",
                inst_id=decision.inst_id,
                payload={
                    "rule_id": RULE_ID,
                    "state": "triggered",
                    "alert": alert,
                },
                occurred_at=decision.occurred_at,
            )
        )

    return rule_engine


@dataclass(frozen=True, slots=True)
class _Decision:
    """一次越界判定：既有落库需要的字段，也有判定用到的数值。"""

    inst_id: str
    direction: str
    traded: Decimal
    reference: Decimal
    deviation: Decimal
    occurred_at: datetime


def _evaluate(
    inst_id: str,
    payload: dict[str, Any],
    crossed: dict[tuple[str, str], bool],
    *,
    occurred_at: datetime,
) -> tuple[_Decision | None, bool]:
    """按一笔行情更新状态。

    返回值是 `(越界判定, 是否刚刚回落)`：「从阈值内到阈值外」的那一次给判定，
    「从阈值外回到阈值内」的那一次给回落标记，其余两次都为空。
    """

    traded = _decimal(payload.get("last"))
    reference = _decimal(payload.get("index"))
    if traded is None or reference is None:
        return None, False
    found = _divergence(inst_id, traded=traded, reference=reference, moment=occurred_at)
    key = (inst_id, RULE_ID)
    was_outside = crossed.get(key, False)
    if found is None:
        crossed[key] = False
        return None, was_outside
    if was_outside:
        return None, False
    crossed[key] = True
    return (
        _Decision(
            inst_id=inst_id,
            direction="above" if traded > reference else "below",
            traded=traded,
            reference=reference,
            deviation=found.deviation_pct,
            occurred_at=occurred_at,
        ),
        False,
    )


def _divergence(
    inst_id: str,
    *,
    traded: Decimal,
    reference: Decimal,
    moment: datetime,
) -> DivergenceAlert | None:
    """成交价相对指数价的偏离；未达阈值、价格非正或标的键非法时返回 `None`。"""

    if traded <= 0 or reference <= 0:
        return None
    try:
        return divergence(
            Quote(product_key=inst_id, source="okx_index", price=reference, ts=moment),
            Quote(product_key=inst_id, source="okx_last", price=traded, ts=moment),
            threshold_pct=DEVIATION_THRESHOLD_PCT,
        )
    except ValidationError:
        return None


def _expire_pending(inst_id: str, moment: datetime) -> int:
    """条件恢复：把该标的仍待处理的管线提醒改成 `expired`，每条写一条活动。

    与提醒域自己的恢复语义一致（状态改 `expired`、`expires_at` 记恢复时刻、写
    `alert.expired` 活动），但只碰本规则的行，不介入提醒域的状态机。
    """

    moment = moment.astimezone(UTC).replace(microsecond=0)
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(AlertEventRow)
                .where(
                    AlertEventRow.instrument_id == inst_id,
                    AlertEventRow.rule_id == RULE_ID,
                    AlertEventRow.status.in_(("pending", "acknowledged")),
                )
                .order_by(AlertEventRow.id)
                .with_for_update()
            )
        )
        for row in rows:
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
                    "rule_id": RULE_ID,
                    "instrument_id": inst_id,
                    "previous_status": previous,
                },
            )
        return len(rows)


def _record_alert(decision: _Decision) -> dict[str, Any] | None:
    """写入一条提醒；同一条（同一越界时刻）已存在时返回 `None`。

    字段与 `alert_events` 完全一致，`GET /api/alerts` 与首页提醒卡直接消费这条记录，
    不改提醒域的任何规则与字段。
    """

    moment = decision.occurred_at.astimezone(UTC)
    alert_id = _alert_id(decision.inst_id, moment)
    direction_text = "高于" if decision.direction == "above" else "低于"
    values = {
        "id": alert_id,
        "type": ALERT_TYPE,
        "severity": ALERT_SEVERITY,
        "instrument_id": decision.inst_id,
        "rule_id": RULE_ID,
        "rule_version": RULE_VERSION,
        "title": "价格偏离参考价",
        "detail": (
            f"{decision.inst_id} 最新成交价 {_number(decision.traded)} {direction_text}"
            f" 指数价 {_number(decision.reference)}，偏离 {_number(decision.deviation)}%"
        ),
        "payload_json": json.dumps(
            {
                "last": _number(decision.traded),
                "index": _number(decision.reference),
                "deviation_pct": _number(decision.deviation),
                "threshold_pct": _number(DEVIATION_THRESHOLD_PCT),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        "status": "pending",
        "dedup_key": (
            f"price|{RULE_ID}|{decision.inst_id}|{decision.direction}|{moment.isoformat()}"
        ),
        "triggered_at": moment,
        "expires_at": None,
        "updated_at": moment,
    }
    try:
        with session_scope() as session:
            statement = (
                pg_insert(AlertEventRow)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[AlertEventRow.dedup_key])
                .returning(AlertEventRow.id)
            )
            if session.scalar(statement) is None:
                return None
    except Exception:  # 落库失败只记录：推送本身不能因为库故障中断
        logger.exception("提醒落库失败: inst=%s", decision.inst_id)
        return None
    return {
        "id": alert_id,
        "type": ALERT_TYPE,
        "severity": ALERT_SEVERITY,
        "instrument_id": decision.inst_id,
        "rule_id": RULE_ID,
        "rule_version": RULE_VERSION,
        "title": values["title"],
        "detail": values["detail"],
        "payload": json.loads(str(values["payload_json"])),
        "status": "pending",
        "triggered_at": moment.isoformat(),
        "expires_at": None,
    }


def _alert_id(inst_id: str, moment: datetime) -> str:
    """提醒标识：标的 + 越界时刻，同一笔越界重放也不会产生第二个标识。"""

    stamp = moment.strftime("%Y%m%d%H%M%S%f")
    return f"al_{inst_id[:20]}_{stamp}"[:64]


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _number(value: Decimal) -> str:
    return format(value.normalize(), "f")

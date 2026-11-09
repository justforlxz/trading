"""opportunity 域的只读视图（列表、详情、市场截面）。

Web API 与 MCP 共用同一份查询与序列化代码：同一批机会在两个入口必须一致，
各写一份迟早漂移。本模块只读，不写任何表，也不做协议层错误翻译
（`InvalidCursor` 由调用方按各自协议转成 422 或 tools/call 的 `isError`）。
"""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.core.opportunities import assert_explainable, market_breadth
from app.market.core.calendar import session_phase
from app.market.models import Instrument
from app.opportunity.models import Opportunity, OpportunityRun
from app.research.models import MarketSnapshot

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class InvalidCursor(ValueError):
    """分页游标不是本域签发的格式；调用方负责翻译成自己的协议错误。"""


def dec_text(value: Any | None) -> str | None:
    """Decimal 一律以字符串返回，避免前端 JSON 解析丢精度。"""

    return None if value is None else str(value)


def iso_text(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def symbol_text(inst_id: str, uly: str | None) -> str:
    return (uly or inst_id.split("-")[0]).upper()


def opportunity_payload(row: Opportunity, instrument: Instrument | None) -> dict[str, Any]:
    """单条机会；`reasons` 与 `evidence` 原样透出，绝不返回裸分数。

    构造时再校验一次可解释性：即使库里被人为写入残缺记录，响应也不会
    悄悄变成一条只有分数的「黑箱」机会。
    """

    assert_explainable(row.reasons or [], row.evidence or {})
    return {
        "id": row.id,
        "run_id": row.run_id,
        "kind": row.kind,
        "direction": row.direction,
        "score": dec_text(row.score),
        "horizon": row.horizon,
        "reasons": row.reasons,
        "evidence": row.evidence,
        "primary_instrument_id": row.primary_instrument_id,
        "primary_inst_id": None if instrument is None else instrument.inst_id,
        "primary_symbol": None
        if instrument is None
        else symbol_text(instrument.inst_id, instrument.uly),
        "created_at": iso_text(row.created_at),
    }


def run_payload(row: OpportunityRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_key": row.run_key,
        "as_of": iso_text(row.as_of),
        "universe_size": row.universe_size,
        "status": row.status,
        "started_at": iso_text(row.started_at),
        "finished_at": iso_text(row.finished_at),
        "error": row.error,
        "params": row.params,
        "counts": row.counts,
    }


def encode_cursor(score: Decimal, row_id: int) -> str:
    raw = f"{score}:{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(value: str) -> tuple[Decimal, int]:
    try:
        decoded = base64.urlsafe_b64decode(value.encode()).decode()
        score_text, id_text = decoded.split(":", 1)
        return Decimal(score_text), int(id_text)
    except (ValueError, UnicodeDecodeError, binascii.Error) as error:
        raise InvalidCursor("cursor is not a valid scan cursor") from error


async def latest_run_id(session: AsyncSession) -> int | None:
    """最新一次成功（含部分成功）批次的 id；没有任何批次时为 None。"""

    return await session.scalar(
        select(func.max(OpportunityRun.id)).where(OpportunityRun.status.in_(["ok", "partial"]))
    )


async def list_opportunities_view(
    session: AsyncSession,
    *,
    run_id: int | None = None,
    kind: str | None = None,
    direction: str | None = None,
    min_score: float | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> dict[str, Any]:
    """按分数倒序返回机会；默认取最新批次，每条都带 `reasons` 与 `evidence`。"""

    if run_id is None:
        run_id = await latest_run_id(session)
        if run_id is None:
            return {"items": [], "next_cursor": None, "run_id": None}

    stmt = (
        select(Opportunity, Instrument)
        .join(Instrument, Instrument.id == Opportunity.primary_instrument_id)
        .where(Opportunity.run_id == run_id)
        .order_by(Opportunity.score.desc(), Opportunity.id.desc())
    )
    if kind is not None:
        stmt = stmt.where(Opportunity.kind == kind)
    if direction is not None:
        stmt = stmt.where(Opportunity.direction == direction)
    if min_score is not None:
        stmt = stmt.where(Opportunity.score >= Decimal(str(min_score)))
    if cursor is not None:
        last_score, last_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Opportunity.score < last_score,
                and_(Opportunity.score == last_score, Opportunity.id < last_id),
            )
        )
    rows = (await session.execute(stmt.limit(limit + 1))).all()
    visible = rows[:limit]
    next_cursor = (
        encode_cursor(visible[-1][0].score, visible[-1][0].id)
        if len(rows) > limit and visible
        else None
    )
    return {
        "run_id": run_id,
        "items": [opportunity_payload(row, instrument) for row, instrument in visible],
        "next_cursor": next_cursor,
    }


async def get_opportunity_view(session: AsyncSession, opportunity_id: int) -> dict[str, Any] | None:
    """单条机会详情（附带成员）；不存在时返回 None，由调用方决定 404 形态。"""

    row = (
        await session.execute(
            select(Opportunity, Instrument)
            .join(Instrument, Instrument.id == Opportunity.primary_instrument_id)
            .where(Opportunity.id == opportunity_id)
        )
    ).first()
    if row is None:
        return None
    opportunity, instrument = row
    payload = opportunity_payload(opportunity, instrument)
    payload["members"] = opportunity.evidence.get("members", []) if opportunity.evidence else []
    return payload


async def market_snapshot_view(
    session: AsyncSession, *, as_of: datetime | None = None
) -> dict[str, Any]:
    """全市场特征截面（驾驶舱数据源）；`as_of` 缺省取最新一次扫描的截面。"""

    moment = as_of or await session.scalar(select(func.max(MarketSnapshot.as_of)))
    if moment is None:
        return {
            "as_of": None,
            "items": [],
            "count": 0,
            "breadth": None,
            "session": session_phase(datetime.now(UTC)),
        }
    rows = (
        await session.execute(
            select(MarketSnapshot, Instrument)
            .join(Instrument, Instrument.id == MarketSnapshot.instrument_id)
            .where(MarketSnapshot.as_of == moment)
            .order_by(Instrument.inst_id)
        )
    ).all()
    items = [
        {
            "instrument_id": snapshot.instrument_id,
            "inst_id": instrument.inst_id,
            "symbol": symbol_text(instrument.inst_id, instrument.uly),
            "asset_class": instrument.asset_class,
            "ret_1d": dec_text(snapshot.ret_1d),
            "ret_5d": dec_text(snapshot.ret_5d),
            "ret_20d": dec_text(snapshot.ret_20d),
            "vol_20d": dec_text(snapshot.vol_20d),
            "atr_14": dec_text(snapshot.atr_14),
            "volume_z": dec_text(snapshot.volume_z),
            "high_20d": dec_text(snapshot.high_20d),
            "low_20d": dec_text(snapshot.low_20d),
            "extras": snapshot.extras,
        }
        for snapshot, instrument in rows
    ]
    returns = [float(snapshot.ret_1d) for snapshot, _ in rows if snapshot.ret_1d is not None]
    return {
        "as_of": iso_text(moment),
        "count": len(items),
        "breadth": market_breadth(returns),
        # 美股时段由市场日历纯函数给出，前端只负责展示，不自己算时区与窗口。
        "session": session_phase(datetime.now(UTC)),
        "items": items,
    }


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "InvalidCursor",
    "dec_text",
    "decode_cursor",
    "encode_cursor",
    "get_opportunity_view",
    "iso_text",
    "latest_run_id",
    "list_opportunities_view",
    "market_snapshot_view",
    "opportunity_payload",
    "run_payload",
    "symbol_text",
]

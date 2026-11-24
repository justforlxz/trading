"""提醒与活动契约：列表筛选、确认/忽略提醒、活动流水。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import UtcDatetime

__all__ = [
    "ActivityItem",
    "ActivityListResponse",
    "AlertItem",
    "AlertListResponse",
    "AlertSeverity",
    "AlertStatus",
    "AlertStatusUpdateRequest",
    "AlertType",
]

AlertType = Literal["indicator", "price", "risk", "strategy", "data", "market", "watchlist"]
AlertSeverity = Literal["info", "warning", "critical"]
AlertStatus = Literal["pending", "acknowledged", "ignored", "expired"]

_EXAMPLE_ALERT = {
    "id": "al_0001",
    "type": "risk",
    "severity": "warning",
    "instrument_id": "XAAPL-USDT",
    "rule_id": "stop_missing",
    "rule_version": "b3-exposure-v1",
    "title": "持仓缺少止损",
    "detail": "XAAPL-USDT 没有有效止损记录",
    "payload": {"position_ref": "manual:0001"},
    "status": "pending",
    "triggered_at": "2026-11-10T23:00:00Z",
    "expires_at": None,
}


class AlertItem(BaseModel):
    id: str
    type: AlertType
    severity: AlertSeverity
    instrument_id: str | None = None
    rule_id: str
    rule_version: str | None = None
    title: str
    detail: str
    payload: dict[str, Any]
    status: AlertStatus
    triggered_at: UtcDatetime
    expires_at: UtcDatetime | None = None

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_ALERT]})


class AlertListResponse(BaseModel):
    items: list[AlertItem]
    next_cursor: str | None = None

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [_EXAMPLE_ALERT], "next_cursor": None}]}
    )


class AlertStatusUpdateRequest(BaseModel):
    status: Literal["acknowledged", "ignored"]


_EXAMPLE_ACTIVITY = {
    "id": "ac_0001",
    "event_type": "research_note.created",
    "object_type": "research_note",
    "object_id": "rn_0001",
    "summary": "创建研究记录「AAPL 假设」",
    "payload": {"type": "hypothesis"},
    "created_at": "2026-11-10T23:00:00Z",
}


class ActivityItem(BaseModel):
    id: str
    event_type: str
    object_type: str
    object_id: str
    summary: str
    payload: dict[str, Any]
    created_at: UtcDatetime

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE_ACTIVITY]})


class ActivityListResponse(BaseModel):
    items: list[ActivityItem]
    next_cursor: str | None = None

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [_EXAMPLE_ACTIVITY], "next_cursor": None}]}
    )

"""提醒与活动端点。

提醒列表在默认的 `pending` 查询前执行一次规则扫描：扫描是提醒的唯一生成入口，
由本接口触发，去重键保证同一标的、同一规则、同一 bar 只落一条。首页只读提醒表，
不在聚合请求里写库。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime

from app.activity import list_activity
from app.alerts import AlertRecord, list_alerts, scan_alerts, update_alert_status
from app.api.schemas import (
    ActivityItem,
    ActivityListResponse,
    AlertItem,
    AlertListResponse,
    AlertStatusUpdateRequest,
)

__all__ = ["alerts_router"]

alerts_router = APIRouter(tags=["alerts"])


@alerts_router.get("/alerts", response_model=AlertListResponse)
def get_alerts(
    status: str | None = Query("pending"),
    type: str | None = Query(None),
    severity: str | None = Query(None),
    instrument_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
) -> AlertListResponse:
    """按状态、类型、级别与标的筛选提醒；默认只返回待处理提醒。"""

    if status in (None, "pending"):
        scan_alerts()
    records, next_cursor = list_alerts(
        status=status,
        type=type,
        severity=severity,
        instrument_id=instrument_id,
        limit=limit,
        cursor=cursor,
    )
    return AlertListResponse(items=[_alert(record) for record in records], next_cursor=next_cursor)


@alerts_router.patch("/alerts/{alert_id}", response_model=AlertItem)
def patch_alert(alert_id: str, payload: AlertStatusUpdateRequest) -> AlertItem:
    """确认或忽略一条待处理提醒；处置结果写一条活动。"""

    record = update_alert_status(alert_id, payload.status)
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到提醒 {alert_id}")
    return _alert(record)


@alerts_router.get("/activity", response_model=ActivityListResponse)
def get_activity(
    event_type: str | None = Query(None),
    object_type: str | None = Query(None),
    start: AwareDatetime | None = Query(None, alias="from"),
    end: AwareDatetime | None = Query(None, alias="to"),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
) -> ActivityListResponse:
    """按时间倒序返回活动流水，可按事件类型与对象类型筛选。"""

    records, next_cursor = list_activity(
        event_type=event_type,
        object_type=object_type,
        start=start,
        end=end,
        limit=limit,
        cursor=cursor,
    )
    return ActivityListResponse(
        items=[
            ActivityItem(
                id=record.id,
                event_type=record.event_type,
                object_type=record.object_type,
                object_id=record.object_id,
                summary=record.summary,
                payload=dict(record.payload),
                created_at=record.created_at,
            )
            for record in records
        ],
        next_cursor=next_cursor,
    )


def _alert(record: AlertRecord) -> AlertItem:
    return AlertItem(
        id=record.id,
        type=record.type,  # type: ignore[arg-type]
        severity=record.severity,  # type: ignore[arg-type]
        instrument_id=record.instrument_id,
        rule_id=record.rule_id,
        rule_version=record.rule_version,
        title=record.title,
        detail=record.detail,
        payload=dict(record.payload),
        status=record.status,  # type: ignore[arg-type]
        triggered_at=record.triggered_at,
        expires_at=record.expires_at,
    )

"""提醒域：规则候选、去重落库、状态流转与扫描。

跨包只允许 `from app.alerts import ...`。
"""

from app.alerts.model import AlertEventRow
from app.alerts.rules import (
    ALERT_SEVERITIES,
    ALERT_TYPES,
    AlertCandidate,
    technical_candidates,
)
from app.alerts.service import (
    AlertRecord,
    list_alerts,
    record_candidate,
    scan_alerts,
    update_alert_status,
)

__all__ = [
    "ALERT_SEVERITIES",
    "ALERT_TYPES",
    "AlertCandidate",
    "AlertEventRow",
    "AlertRecord",
    "list_alerts",
    "record_candidate",
    "scan_alerts",
    "technical_candidates",
    "update_alert_status",
]

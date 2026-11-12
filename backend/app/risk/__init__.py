"""风控：两层限额、按类别适用、紧急停止、分级处置与风险事件（P2）。

门面即出口：跨包只允许 `from app.risk import ...`。
"""

from app.risk.actions import (
    DisposalRequest,
    dispose,
)
from app.risk.disposal import (
    DisposalAction,
    DisposalContext,
    Severity,
    plan,
)
from app.risk.rules import (
    Correlation,
    PositionExposure,
    RiskContext,
    RiskLimits,
    SignalRecord,
    TradeRequest,
    applicable_rule_names,
    evaluate,
    rule_applicability,
)
from app.risk.service import (
    RiskEngine,
    list_risk_events,
    resolve_risk_event,
)

__all__ = [
    "Correlation",
    "DisposalAction",
    "DisposalContext",
    "DisposalRequest",
    "PositionExposure",
    "RiskContext",
    "RiskEngine",
    "RiskLimits",
    "Severity",
    "SignalRecord",
    "TradeRequest",
    "applicable_rule_names",
    "dispose",
    "evaluate",
    "list_risk_events",
    "plan",
    "resolve_risk_event",
    "rule_applicability",
]

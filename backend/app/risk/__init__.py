"""风控：两层限额、按类别适用、紧急停止与风险事件（P2）。

门面即出口：跨包只允许 `from app.risk import ...`。
"""

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
from app.risk.service import RiskEngine, list_risk_events

__all__ = [
    "Correlation",
    "PositionExposure",
    "RiskContext",
    "RiskEngine",
    "RiskLimits",
    "SignalRecord",
    "TradeRequest",
    "applicable_rule_names",
    "evaluate",
    "list_risk_events",
    "rule_applicability",
]

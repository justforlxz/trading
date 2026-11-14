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
from app.risk.exposure import (
    RULE_HIGH_LEVERAGE,
    RULE_MARGIN_USAGE,
    RULE_SINGLE_INSTRUMENT_WEIGHT,
    RULE_STOP_DISTANCE,
    RULE_STOP_MISSING,
    PositionRiskInput,
    RiskExposure,
    RiskThresholds,
    build_exposure,
    notional_value,
)
from app.risk.exposure_service import (
    SavedRiskConfig,
    exposure_report,
    save_position_risk_config,
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
    list_unresolved_risk_events,
    resolve_risk_event,
)

__all__ = [
    "RULE_HIGH_LEVERAGE",
    "RULE_MARGIN_USAGE",
    "RULE_SINGLE_INSTRUMENT_WEIGHT",
    "RULE_STOP_DISTANCE",
    "RULE_STOP_MISSING",
    "Correlation",
    "DisposalAction",
    "DisposalContext",
    "DisposalRequest",
    "PositionExposure",
    "PositionRiskInput",
    "RiskContext",
    "RiskEngine",
    "RiskExposure",
    "RiskLimits",
    "RiskThresholds",
    "SavedRiskConfig",
    "Severity",
    "SignalRecord",
    "TradeRequest",
    "applicable_rule_names",
    "build_exposure",
    "dispose",
    "evaluate",
    "exposure_report",
    "list_risk_events",
    "list_unresolved_risk_events",
    "notional_value",
    "plan",
    "resolve_risk_event",
    "rule_applicability",
    "save_position_risk_config",
]

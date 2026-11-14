"""风险与敞口契约：持仓级风险、行业汇总、规则结果与本地风险配置。

所有金额、价格和百分比都以字符串承载十进制数；没有行情或无法计算的字段为
`null`，不用 0 或相似标的冒充。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import DecimalString, PositionSide, UtcDatetime

__all__ = [
    "ExposurePositionItem",
    "ExposureRuleItem",
    "ExposureSummary",
    "PositionRiskConfigResponse",
    "RiskConfigUpdateRequest",
    "RiskExposureResponse",
    "SectorExposureItem",
]

RiskLevel = Literal["low", "medium", "high"]
RuleLevel = Literal["warning", "critical"]
ExposureStatus = Literal["ok", "empty"]
MarginUsageBasis = Literal["margin_ratio", "used_margin"]


class ExposureSummary(BaseModel):
    long_notional: DecimalString
    short_notional: DecimalString
    net_notional: DecimalString
    gross_notional: DecimalString
    margin_usage_pct: DecimalString | None = None
    margin_usage_basis: MarginUsageBasis | None = None
    risk_level: RiskLevel
    currency: str


class ExposurePositionItem(BaseModel):
    position_ref: str
    source: Literal["exchange", "manual"]
    inst_id: str
    display_symbol: str
    side: PositionSide
    notional: DecimalString | None = None
    weight_pct: DecimalString | None = None
    mark_px: DecimalString | None = None
    stop_px: DecimalString | None = None
    stop_distance_pct: DecimalString | None = None
    atr_distance: DecimalString | None = None
    lever: DecimalString | None = None
    flags: list[str]


class SectorExposureItem(BaseModel):
    sector: str
    notional: DecimalString
    weight_pct: DecimalString


class ExposureRuleItem(BaseModel):
    rule_id: str
    level: RuleLevel
    position_ref: str | None = None
    value: DecimalString | None = None
    threshold: DecimalString | None = None


class RiskExposureResponse(BaseModel):
    as_of: UtcDatetime
    status: ExposureStatus
    summary: ExposureSummary
    positions: list[ExposurePositionItem]
    sectors: list[SectorExposureItem]
    rules: list[ExposureRuleItem]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "as_of": "2026-11-13T09:00:00Z",
                    "status": "ok",
                    "summary": {
                        "long_notional": "3412.80",
                        "short_notional": "980.40",
                        "net_notional": "2432.40",
                        "gross_notional": "4393.20",
                        "margin_usage_pct": "45.36",
                        "margin_usage_basis": "margin_ratio",
                        "risk_level": "low",
                        "currency": "USDT",
                    },
                    "positions": [
                        {
                            "position_ref": "exchange:okx-main:123456",
                            "source": "exchange",
                            "inst_id": "AAPL-USDT-SWAP",
                            "display_symbol": "AAPL-USDT",
                            "side": "long",
                            "notional": "1851.36",
                            "weight_pct": "42.14",
                            "mark_px": "231.42",
                            "stop_px": "210.00",
                            "stop_distance_pct": "9.25",
                            "atr_distance": "3.8",
                            "lever": "3",
                            "flags": [],
                        }
                    ],
                    "sectors": [
                        {
                            "sector": "semiconductor",
                            "notional": "1200.00",
                            "weight_pct": "27.32",
                        }
                    ],
                    "rules": [
                        {
                            "rule_id": "stop_distance",
                            "level": "warning",
                            "position_ref": "exchange:okx-main:123456",
                            "value": "0.8",
                            "threshold": "1",
                        }
                    ],
                }
            ]
        }
    )


class RiskConfigUpdateRequest(BaseModel):
    """本地风险配置的部分更新；显式传 `null` 表示清除该字段。"""

    model_config = ConfigDict(extra="forbid")

    stop_px: DecimalString | None = None
    risk_budget: DecimalString | None = None
    warning_threshold_pct: DecimalString | None = None


class PositionRiskConfigResponse(BaseModel):
    position_ref: str
    stop_px: DecimalString | None = None
    risk_budget: DecimalString | None = None
    warning_threshold_pct: DecimalString | None = None
    source: str
    updated_at: UtcDatetime

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "position_ref": "exchange:okx-main:123456",
                    "stop_px": "210.00",
                    "risk_budget": "50",
                    "warning_threshold_pct": "1.5",
                    "source": "local",
                    "updated_at": "2026-11-13T09:00:00Z",
                }
            ]
        }
    )

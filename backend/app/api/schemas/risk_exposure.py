"""风险与敞口契约：持仓级风险、行业汇总、规则结果与本地风险配置。

所有金额、价格和百分比都以字符串承载十进制数；没有行情或无法计算的字段为
`null`，不用 0 或相似标的冒充。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import (
    DecimalString,
    MarginUsageBasis,
    PositionSide,
    StopStatus,
    UtcDatetime,
)

__all__ = [
    "ExposurePositionItem",
    "ExposureRuleItem",
    "ExposureSummary",
    "PositionRiskConfigResponse",
    "RiskConfigUpdateRequest",
    "RiskExposureResponse",
    "RiskNotifyConfigResponse",
    "RiskNotifyConfigUpdateRequest",
    "RiskNotifyRuleItem",
    "RiskNotifyRuleUpdate",
    "SectorExposureItem",
]

RiskLevel = Literal["low", "medium", "high"]
RuleLevel = Literal["warning", "critical"]
ExposureStatus = Literal["ok", "empty"]

#: 通知渠道；与 `app.risk.notify.CHANNELS` 一致。
NotifyChannel = Literal["browser", "telegram", "webhook"]


class ExposureSummary(BaseModel):
    long_notional: DecimalString
    short_notional: DecimalString
    net_notional: DecimalString
    gross_notional: DecimalString
    margin_usage_pct: DecimalString | None = None
    margin_usage_basis: MarginUsageBasis | None = None
    max_single_instrument_weight_pct: DecimalString | None = None
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
    #: 止损三态；`None` 表示来源没有这个概念（手动持仓）。`unavailable` 与
    #: `none` 必须分开：前者是我们没查到，后者才确认没挂。
    stop_status: StopStatus | None = None
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
                        "margin_usage_basis": "notional_over_leverage",
                        "max_single_instrument_weight_pct": "42.14",
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
                            "stop_status": "confirmed",
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


class RiskNotifyRuleItem(BaseModel):
    """一条风控通知规则：开关、渠道与阈值。

    阈值为 `null` 的规则（未挂止损）没有可调数字；其余规则的阈值就是敞口计算用的
    那一份，不另存副本。
    """

    rule_id: str
    enabled: bool
    channels: list[NotifyChannel]
    threshold: DecimalString | None = None


class RiskNotifyConfigResponse(BaseModel):
    """五条风控通知规则的完整配置，顺序固定。"""

    rules: list[RiskNotifyRuleItem]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "rules": [
                        {
                            "rule_id": "stop_missing",
                            "enabled": True,
                            "channels": ["browser"],
                            "threshold": None,
                        },
                        {
                            "rule_id": "high_leverage",
                            "enabled": True,
                            "channels": ["browser", "telegram"],
                            "threshold": "5",
                        },
                    ]
                }
            ]
        }
    )


class RiskNotifyRuleUpdate(BaseModel):
    """单条规则的部分更新；未提交的字段保持原值。"""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    enabled: bool | None = None
    channels: list[NotifyChannel] | None = None
    threshold: DecimalString | None = None


class RiskNotifyConfigUpdateRequest(BaseModel):
    """批量更新通知规则；只提交的规则会被改动。"""

    model_config = ConfigDict(extra="forbid")

    rules: list[RiskNotifyRuleUpdate]

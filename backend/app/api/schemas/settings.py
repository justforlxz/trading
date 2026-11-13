"""设置契约：分组的可持久化配置。

交易所 API Key 只写不读：响应只带「是否已配置」与全掩码，明文永不进入 HTTP。
Secret 与 Passphrase 仍只经环境变量注入，不在本契约的可写范围内。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.api.schemas.common import Bar, DecimalString, ExecutionMode, UtcDatetime

__all__ = [
    "BacktestSettings",
    "CostSettings",
    "DataSettings",
    "ExchangeSettings",
    "ExchangeSettingsUpdate",
    "ExecutionSettings",
    "RiskSettings",
    "SettingsResponse",
    "SettingsUpdateRequest",
]


class ExecutionSettings(BaseModel):
    mode: ExecutionMode
    auto_trading_enabled: bool
    emergency_stop: bool


class RiskSettings(BaseModel):
    """风控限额。`max_leverage` 的硬上限（10）不因配置抬高（decisions.md L1）。"""

    max_order_notional: DecimalString
    max_position_notional: DecimalString
    max_total_notional: DecimalString
    max_positions: int
    max_leverage: DecimalString
    max_daily_loss: DecimalString
    liquidation_buffer_pct: DecimalString
    stop_loss_mandatory: bool

    @model_validator(mode="after")
    def _check_leverage(self) -> RiskSettings:
        try:
            leverage = Decimal(self.max_leverage)
        except InvalidOperation as exc:
            raise ValueError("max_leverage 必须是十进制数") from exc
        if not Decimal(1) <= leverage <= Decimal(10):
            raise ValueError("max_leverage 必须在 1 到 10 之间")
        return self


class CostSettings(BaseModel):
    maker_fee_bps: DecimalString
    taker_fee_bps: DecimalString
    slippage_bps: DecimalString
    spread_bps: DecimalString


class BacktestSettings(BaseModel):
    funding_enabled: bool
    default_initial_capital: DecimalString
    default_bar: Bar


class ExchangeSettings(BaseModel):
    demo_trading: bool
    api_configured: bool
    api_key_masked: str | None = None


class ExchangeSettingsUpdate(BaseModel):
    """只写字段：提交后服务端只保存，不读回明文。"""

    api_key: SecretStr | None = Field(default=None, min_length=1)


class DataSettings(BaseModel):
    proxy_enabled: bool
    proxy_configured: bool


class SettingsResponse(BaseModel):
    execution: ExecutionSettings
    risk: RiskSettings
    costs: CostSettings
    backtest: BacktestSettings
    exchange: ExchangeSettings
    data: DataSettings
    updated_at: UtcDatetime

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "execution": {
                        "mode": "paper",
                        "auto_trading_enabled": False,
                        "emergency_stop": False,
                    },
                    "risk": {
                        "max_order_notional": "1000",
                        "max_position_notional": "3000",
                        "max_total_notional": "10000",
                        "max_positions": 5,
                        "max_leverage": "3",
                        "max_daily_loss": "300",
                        "liquidation_buffer_pct": "10",
                        "stop_loss_mandatory": True,
                    },
                    "costs": {
                        "maker_fee_bps": "2",
                        "taker_fee_bps": "5",
                        "slippage_bps": "3",
                        "spread_bps": "2",
                    },
                    "backtest": {
                        "funding_enabled": True,
                        "default_initial_capital": "10000",
                        "default_bar": "1h",
                    },
                    "exchange": {
                        "demo_trading": True,
                        "api_configured": False,
                        "api_key_masked": None,
                    },
                    "data": {"proxy_enabled": False, "proxy_configured": False},
                    "updated_at": "2026-11-10T06:10:00Z",
                }
            ]
        }
    )


class SettingsUpdateRequest(BaseModel):
    """分组级部分更新；交易所凭据只接受 API Key 写入，Secret 与 Passphrase 仍走环境变量。"""

    model_config = ConfigDict(extra="forbid")

    execution: ExecutionSettings | None = None
    risk: RiskSettings | None = None
    costs: CostSettings | None = None
    backtest: BacktestSettings | None = None
    data: DataSettings | None = None
    exchange: ExchangeSettingsUpdate | None = None
    #: 切到实盘必须显式确认；未带 true 的请求返回 409，且不写入任何分组。
    acknowledge_risk: bool = False

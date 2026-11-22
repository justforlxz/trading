"""设置契约：v6 的显示偏好、风险默认值、自动执行开关、数据源、通知通道与密钥状态。

交易所 API Key 只写不读：响应只带「是否已配置」与全掩码，明文永不进入 HTTP。
Secret 与 Passphrase 仍只经环境变量注入，不在本契约的可写范围内。成本与回测默认值
仍由服务端内部读取，但不属于本契约，前端不能读写。

通知通道同理：Telegram `chat_id` 与 Webhook 接收地址是可读写字段；`TELEGRAM_BOT_TOKEN`
与 `WEBHOOK_SIGNING_SECRET` 只在环境变量里，响应只带 `token_configured` /
`secret_configured` 两个布尔。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.api.schemas.common import Bar, DecimalString, UtcDatetime

__all__ = [
    "DataSourceSettings",
    "DataSourceSettingsUpdate",
    "DeliveryItem",
    "DeliveryListResponse",
    "DisplaySettings",
    "ExchangeSettingsUpdate",
    "ExecutionSettings",
    "NotificationChannelTestRequest",
    "NotificationChannelTestResponse",
    "NotificationSettings",
    "NotificationSettingsUpdate",
    "RiskDefaults",
    "SecretSettings",
    "SettingsResponse",
    "SettingsUpdateRequest",
    "TelegramSettings",
    "TelegramSettingsUpdate",
    "WebhookSettings",
    "WebhookSettingsUpdate",
]

ColorScheme = Literal["system", "light", "dark"]
OkxPermission = Literal["read_only", "unknown"]


class DisplaySettings(BaseModel):
    """显示偏好；前端可缓存，后端持久化。"""

    model_config = ConfigDict(extra="forbid")

    color_scheme: ColorScheme = "system"
    default_bar: Bar = "1d"
    price_precision: int = Field(default=2, ge=0, le=8)
    home_layout: str = Field(default="cockpit", min_length=1, max_length=32)


class RiskDefaults(BaseModel):
    """策略默认风险参数；不是执行风控限额。"""

    model_config = ConfigDict(extra="forbid")

    default_leverage: DecimalString = "3"
    risk_budget_per_trade: DecimalString = "100"
    warning_threshold: DecimalString = "80"
    stop_rule: str = Field(default="fixed_pct", min_length=1, max_length=32)

    @model_validator(mode="after")
    def _check_values(self) -> RiskDefaults:
        try:
            leverage = Decimal(self.default_leverage)
            budget = Decimal(self.risk_budget_per_trade)
            threshold = Decimal(self.warning_threshold)
        except InvalidOperation as exc:
            raise ValueError("风险默认值必须是十进制数") from exc
        if not Decimal(1) <= leverage <= Decimal(10):
            raise ValueError("default_leverage 必须在 1 到 10 之间")
        if budget < 0:
            raise ValueError("risk_budget_per_trade 不能为负数")
        if not Decimal(0) <= threshold <= Decimal(100):
            raise ValueError("warning_threshold 必须在 0 到 100 之间")
        return self


class ExecutionSettings(BaseModel):
    """自动执行开关：v6 默认关闭，只保存状态，不产生真实订单。"""

    model_config = ConfigDict(extra="forbid")

    auto_trading_enabled: bool = False


class DataSourceSettings(BaseModel):
    """数据源配置与同步状态；状态字段由服务端读取同步任务表填写。"""

    subscribed_instruments: list[str] = Field(default_factory=list)
    last_sync_at: UtcDatetime | None = None
    failure_count: int = Field(default=0, ge=0)


class DataSourceSettingsUpdate(BaseModel):
    """数据源可写字段；最后同步时间与失败次数只读。"""

    subscribed_instruments: list[str] | None = None

    model_config = ConfigDict(extra="forbid")


class TelegramSettings(BaseModel):
    """Telegram 接收方：`chat_id` 可读写，token 只报「是否已配置」。"""

    model_config = ConfigDict(extra="forbid")

    chat_id: str = ""
    token_configured: bool = False


class WebhookSettings(BaseModel):
    """Webhook 接收方：地址可读写，签名密钥只报「是否已配置」。"""

    model_config = ConfigDict(extra="forbid")

    url: str = ""
    secret_configured: bool = False


class NotificationSettings(BaseModel):
    """通知通道开关与两个可编辑的接收方；三个通道都可独立开关。"""

    model_config = ConfigDict(extra="forbid")

    channels: list[str] = Field(default_factory=lambda: ["browser"])
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    webhook: WebhookSettings = Field(default_factory=WebhookSettings)


class TelegramSettingsUpdate(BaseModel):
    """Telegram 可写字段：只有 `chat_id`。空字符串表示「清空接收方」。"""

    model_config = ConfigDict(extra="forbid")

    chat_id: str = Field(default="", max_length=64)


class WebhookSettingsUpdate(BaseModel):
    """Webhook 可写字段：只有接收地址，必须是 http 或 https。"""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(default="", max_length=2048)

    @field_validator("url")
    @classmethod
    def _check_scheme(cls, value: str) -> str:
        url = value.strip()
        if url and urlparse(url).scheme not in _ALLOWED_SCHEMES:
            raise ValueError("Webhook 接收地址必须是 http 或 https 地址")
        return url


class NotificationSettingsUpdate(BaseModel):
    """按子项改通知设置：不提交的子项保持原值，空通道清单表示一个通道都不开。"""

    model_config = ConfigDict(extra="forbid")

    channels: list[str] | None = None
    telegram: TelegramSettingsUpdate | None = None
    webhook: WebhookSettingsUpdate | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> NotificationSettingsUpdate:
        if self.channels is None and self.telegram is None and self.webhook is None:
            raise ValueError("通知设置至少提交一个子项")
        return self


#: 接收地址允许的协议：只接受明文与 TLS 两种 HTTP 协议。
_ALLOWED_SCHEMES = frozenset({"http", "https"})

NotificationChannel = Literal["telegram", "webhook"]


class NotificationChannelTestRequest(BaseModel):
    """测试发送：只针对两个外部通道，浏览器通道不需要（页面自己就能验证）。"""

    model_config = ConfigDict(extra="forbid")

    channel: NotificationChannel


class NotificationChannelTestResponse(BaseModel):
    """测试发送的结果：与投递台账同一套状态与失败原因。"""

    channel: str
    status: Literal["delivered", "failed"]
    error: str | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"channel": "telegram", "status": "delivered", "error": None},
            ]
        }
    )


class DeliveryItem(BaseModel):
    """一行投递台账：哪条告警、走哪个通道、成没成、失败原因与时间。"""

    id: str
    channel: str
    alert_id: str | None = None
    status: Literal["delivered", "failed"]
    error: str | None = None
    created_at: UtcDatetime


class DeliveryListResponse(BaseModel):
    """最近若干条投递记录，新的在前；条数由查询上限限制，不做定期清理。"""

    items: list[DeliveryItem] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "id": "nd_3f9c1a7b5e2d4c6f8a0b1c2d",
                            "channel": "telegram",
                            "alert_id": "al_XAAPL-USDT_20261120120000000000",
                            "status": "delivered",
                            "error": None,
                            "created_at": "2026-11-20T12:00:03Z",
                        }
                    ]
                }
            ]
        }
    )


class SecretSettings(BaseModel):
    """密钥状态：只读，永不返回明文。"""

    okx_api_key_masked: str | None = None
    okx_configured: bool
    okx_permission: OkxPermission | None = None


class ExchangeSettingsUpdate(BaseModel):
    """API Key 只写字段；提交后服务端只保存，不读回明文。"""

    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr | None = Field(default=None, min_length=1)


class SettingsResponse(BaseModel):
    display: DisplaySettings
    risk_defaults: RiskDefaults
    execution: ExecutionSettings
    data_sources: DataSourceSettings
    notifications: NotificationSettings
    secrets: SecretSettings
    updated_at: UtcDatetime

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "display": {
                        "color_scheme": "system",
                        "default_bar": "1d",
                        "price_precision": 2,
                        "home_layout": "cockpit",
                    },
                    "risk_defaults": {
                        "default_leverage": "3",
                        "risk_budget_per_trade": "100",
                        "warning_threshold": "80",
                        "stop_rule": "fixed_pct",
                    },
                    "execution": {"auto_trading_enabled": False},
                    "data_sources": {
                        "subscribed_instruments": [],
                        "last_sync_at": None,
                        "failure_count": 0,
                    },
                    "notifications": {
                        "channels": ["browser"],
                        "telegram": {"chat_id": "", "token_configured": False},
                        "webhook": {"url": "", "secret_configured": False},
                    },
                    "secrets": {
                        "okx_api_key_masked": None,
                        "okx_configured": False,
                        "okx_permission": None,
                    },
                    "updated_at": "2026-11-15T06:10:00Z",
                }
            ]
        }
    )


class SettingsUpdateRequest(BaseModel):
    """分组级部分更新，至少提交一项；`secrets` 只读，不在本模型里。"""

    model_config = ConfigDict(extra="forbid")

    display: DisplaySettings | None = None
    risk_defaults: RiskDefaults | None = None
    execution: ExecutionSettings | None = None
    data_sources: DataSourceSettingsUpdate | None = None
    notifications: NotificationSettingsUpdate | None = None
    exchange: ExchangeSettingsUpdate | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> SettingsUpdateRequest:
        if not any(
            value is not None
            for value in (
                self.display,
                self.risk_defaults,
                self.execution,
                self.data_sources,
                self.notifications,
                self.exchange,
            )
        ):
            raise ValueError("至少提交一个设置分组")
        return self

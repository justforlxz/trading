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
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.alerts import ALERT_TYPES
from app.api.schemas.common import Bar, DecimalString, UtcDatetime
from app.events import DEFAULT_SUBSCRIPTIONS

__all__ = [
    "ChannelSubscriptionSettings",
    "ChannelSubscriptionUpdate",
    "DataSourceSettings",
    "DataSourceSettingsUpdate",
    "DeliveryItem",
    "DeliveryListResponse",
    "DisplaySettings",
    "DisplaySettingsUpdate",
    "EquitySchedulerSettings",
    "EquitySchedulerSettingsUpdate",
    "EquitySettings",
    "EquitySettingsUpdate",
    "ExchangeSettingsUpdate",
    "ExecutionSettings",
    "NotificationChannelTestRequest",
    "NotificationChannelTestResponse",
    "NotificationSettings",
    "NotificationSettingsUpdate",
    "NotificationSubscriptions",
    "NotificationSubscriptionsUpdate",
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


#: 首页「关注列表」卡片置顶清单的可写形状。
#:
#: 对外仍是 `array<string>`（`json_schema_extra` 保证导出的契约与前端类型不变），
#: 但运行时的形状校验交给路由层，好让「不是数组」「元素不是字符串」与「超过 5 个」
#: 「有重复」「不在自选里」一样返回 400。若这里声明成 `list[str]`，非数组会在到达
#: 路由前被 FastAPI 判成 422，数字元素还会被宽松模式悄悄转成字符串。
HomepagePinned = Annotated[
    Any, Field(json_schema_extra={"type": "array", "items": {"type": "string"}})
]


class DisplaySettings(BaseModel):
    """显示偏好；前端可缓存，后端持久化。"""

    model_config = ConfigDict(extra="forbid")

    color_scheme: ColorScheme = "system"
    default_bar: Bar = "1d"
    price_precision: int = Field(default=2, ge=0, le=8)
    home_layout: str = Field(default="cockpit", min_length=1, max_length=32)
    #: 首页「关注列表」卡片置顶的标的，按选择顺序，最多 5 个；空表示卡片显示空状态。
    homepage_pinned: list[str] = Field(default_factory=list)


class DisplaySettingsUpdate(BaseModel):
    """显示偏好的可写字段：不提交的字段保持库中原值。

    置顶清单的取值规则（形状、长度、重复、是否在自选里）由路由层校验，因此这里
    只声明形状、不加约束；`None` 表示本次不改这一项。
    """

    model_config = ConfigDict(extra="forbid")

    color_scheme: ColorScheme | None = None
    default_bar: Bar | None = None
    price_precision: int | None = Field(default=None, ge=0, le=8)
    home_layout: str | None = Field(default=None, min_length=1, max_length=32)
    homepage_pinned: HomepagePinned | None = None


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


#: 已实现的宏观 provider 名；未登记的名字在写侧直接 422，不落进设置文档。
MacroProviderName = Literal["treasury", "cboe", "yahoo"]
#: 允许的调度周期。
MacroInterval = Literal["1m", "5m"]


class MacroSeriesSettings(BaseModel):
    """一个序列两个粒度的当前 provider；没有配置的粒度给 `null`。"""

    minute: str | None = None
    daily: str | None = None


class MacroSchedulerSettings(BaseModel):
    """宏观调度周期：`1m` / `5m`。"""

    minute: str


class MacroSettings(BaseModel):
    """宏观数据源配置的只读视图；上游地址属于服务端内部参数，不经 HTTP 暴露。"""

    series: dict[str, MacroSeriesSettings]
    scheduler: MacroSchedulerSettings


class MacroSeriesSettingsUpdate(BaseModel):
    """按粒度切换 provider；只提交改动的那一项。"""

    minute: MacroProviderName | None = None
    daily: MacroProviderName | None = None

    model_config = ConfigDict(extra="forbid")


class MacroSchedulerSettingsUpdate(BaseModel):
    """调度周期，只接受实现支持的取值。"""

    minute: MacroInterval | None = None

    model_config = ConfigDict(extra="forbid")


class MacroSettingsUpdate(BaseModel):
    """宏观分组的可写字段；未提交的序列与子项保持原值。"""

    series: dict[str, MacroSeriesSettingsUpdate] | None = None
    scheduler: MacroSchedulerSettingsUpdate | None = None

    model_config = ConfigDict(extra="forbid")


#: 已实现的美股 provider 名；未登记的名字在写侧直接 422，不落进设置文档。
EquityProviderName = Literal["yahoo", "stooq"]


class EquitySchedulerSettings(BaseModel):
    """美股调度周期：`1m` / `5m`。"""

    minute: str


class EquitySettings(BaseModel):
    """美股数据源的只读视图；周期由 provider 声明，因此不在这里配置。"""

    provider: str
    symbols: list[str] = Field(default_factory=list)
    scheduler: EquitySchedulerSettings


class EquitySchedulerSettingsUpdate(BaseModel):
    """调度周期，只接受实现支持的取值。"""

    minute: MacroInterval | None = None

    model_config = ConfigDict(extra="forbid")


class EquitySettingsUpdate(BaseModel):
    """美股分组的可写字段；未提交的子项保持原值，标的清单整体替换。"""

    provider: EquityProviderName | None = None
    symbols: list[str] | None = None
    scheduler: EquitySchedulerSettingsUpdate | None = None

    model_config = ConfigDict(extra="forbid")


class DataSourceSettings(BaseModel):
    """数据源配置与同步状态；状态字段由服务端读取同步任务表填写。"""

    subscribed_instruments: list[str] = Field(default_factory=list)
    last_sync_at: UtcDatetime | None = None
    failure_count: int = Field(default=0, ge=0)
    macro: MacroSettings
    equity: EquitySettings


class DataSourceSettingsUpdate(BaseModel):
    """数据源可写字段；最后同步时间与失败次数只读。"""

    subscribed_instruments: list[str] | None = None
    macro: MacroSettingsUpdate | None = None
    equity: EquitySettingsUpdate | None = None

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


#: 提醒严重度，与 `app.alerts.rules.ALERT_SEVERITIES` 同一组取值。
AlertSeverity = Literal["info", "warning", "critical"]


class ChannelSubscriptionSettings(BaseModel):
    """一个通道的订阅：收哪几类提醒、最低到什么严重度才收。"""

    model_config = ConfigDict(extra="forbid")

    types: list[str] = Field(default_factory=list)
    min_severity: AlertSeverity = "info"

    @field_validator("types")
    @classmethod
    def _check_types(cls, value: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        unknown = [item for item in cleaned if item not in ALERT_TYPES]
        if unknown:
            raise ValueError(
                f"未知提醒类型: {', '.join(unknown)}；可选值: {', '.join(ALERT_TYPES)}"
            )
        return cleaned


def _default_subscription(channel: str) -> ChannelSubscriptionSettings:
    return ChannelSubscriptionSettings(**DEFAULT_SUBSCRIPTIONS[channel])


class ChannelSubscriptionUpdate(BaseModel):
    """一个通道的订阅写入：只覆盖提交出来的字段，未提交的字段保持库中原值。"""

    model_config = ConfigDict(extra="forbid")

    types: list[str] | None = None
    min_severity: AlertSeverity | None = None

    @field_validator("types")
    @classmethod
    def _check_types(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else ChannelSubscriptionSettings._check_types(value)

    @model_validator(mode="after")
    def _at_least_one(self) -> ChannelSubscriptionUpdate:
        if self.types is None and self.min_severity is None:
            raise ValueError("通道订阅至少提交一个字段")
        return self


class NotificationSubscriptions(BaseModel):
    """三个通道各自的订阅；读取时缺项按默认值补齐。"""

    model_config = ConfigDict(extra="forbid")

    browser: ChannelSubscriptionSettings = Field(
        default_factory=lambda: _default_subscription("browser")
    )
    telegram: ChannelSubscriptionSettings = Field(
        default_factory=lambda: _default_subscription("telegram")
    )
    webhook: ChannelSubscriptionSettings = Field(
        default_factory=lambda: _default_subscription("webhook")
    )


class NotificationSubscriptionsUpdate(BaseModel):
    """按通道、按字段部分更新订阅：只提交要改的通道与字段，其余保持原值。"""

    model_config = ConfigDict(extra="forbid")

    browser: ChannelSubscriptionUpdate | None = None
    telegram: ChannelSubscriptionUpdate | None = None
    webhook: ChannelSubscriptionUpdate | None = None

    @model_validator(mode="after")
    def _at_least_one_channel(self) -> NotificationSubscriptionsUpdate:
        if self.browser is None and self.telegram is None and self.webhook is None:
            raise ValueError("订阅至少提交一个通道")
        return self


def _default_subscriptions() -> NotificationSubscriptions:
    """三个通道的默认订阅：与投递侧共用同一份定义，页面显示的就是生效值。"""

    return NotificationSubscriptions()


class NotificationSettings(BaseModel):
    """通知通道开关、两个可编辑的接收方，以及按通道的类型订阅。"""

    model_config = ConfigDict(extra="forbid")

    channels: list[str] = Field(default_factory=lambda: ["browser"])
    subscriptions: NotificationSubscriptions = Field(default_factory=_default_subscriptions)
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
    subscriptions: NotificationSubscriptionsUpdate | None = None
    telegram: TelegramSettingsUpdate | None = None
    webhook: WebhookSettingsUpdate | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> NotificationSettingsUpdate:
        if (
            self.channels is None
            and self.subscriptions is None
            and self.telegram is None
            and self.webhook is None
        ):
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
                        "homepage_pinned": [],
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
                        "macro": {
                            "series": {
                                "us10y": {"minute": "yahoo", "daily": "treasury"},
                                "us2y": {"minute": None, "daily": "treasury"},
                                "vix": {"minute": "yahoo", "daily": "cboe"},
                            },
                            "scheduler": {"minute": "1m"},
                        },
                        "equity": {
                            "provider": "yahoo",
                            "symbols": ["SPY", "QQQ"],
                            "scheduler": {"minute": "1m"},
                        },
                    },
                    "notifications": {
                        "channels": ["browser"],
                        "subscriptions": {
                            "browser": {
                                "types": list(ALERT_TYPES),
                                "min_severity": "info",
                            },
                            "telegram": {"types": ["risk", "strategy"], "min_severity": "warning"},
                            "webhook": {"types": [], "min_severity": "warning"},
                        },
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

    display: DisplaySettingsUpdate | None = None
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

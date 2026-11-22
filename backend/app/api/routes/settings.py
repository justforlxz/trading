"""设置端点：v6 四类设置的唯一 HTTP 出口。

端点只做请求校验与响应组装；持久化、默认值与凭据应用都在 `app.settings` 里。

- `GET /api/settings` 永不返回 API Key 明文，只返回是否已配置与全掩码；
- `PATCH /api/settings` 按分组部分更新，成本与回测默认值不再经 HTTP 暴露；
- 通知通道开关与其余分组一样存在设置文档里，不在仓库里写死；保存后立即应用，
  不用重启进程（`app.events.apply_channels`）；
- 数据源的最后同步时间与失败次数来自 OKX 的 `data_sync_jobs`，不由前端推算；
- Telegram / Webhook 的接收方可读写，`TELEGRAM_BOT_TOKEN` 与 `WEBHOOK_SIGNING_SECRET`
  只读环境变量：响应里只有 `token_configured` / `secret_configured` 两个布尔；
- 测试发送用 `build_channel` 临时构造同一个通道实现投一条测试事件，并把结果写进投递
  台账；「最近投递」读的是同一张表，不做定期清理。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas import (
    DataSourceSettings,
    DeliveryItem,
    DeliveryListResponse,
    DisplaySettings,
    ExecutionSettings,
    MacroSchedulerSettings,
    MacroSeriesSettings,
    MacroSettings,
    NotificationChannelTestRequest,
    NotificationChannelTestResponse,
    NotificationSettings,
    RiskDefaults,
    SecretSettings,
    SettingsResponse,
    SettingsUpdateRequest,
    TelegramSettings,
    WebhookSettings,
)
from app.config import get_settings as runtime_settings
from app.events import (
    ChannelConfig,
    DeliveryResult,
    DomainEvent,
    NotificationDeliveryRow,
    apply_channels,
    build_channel,
    config_from_notifications,
    list_deliveries,
    record_delivery,
)
from app.jobs import OKX_PROVIDER
from app.macro import validate_series_override
from app.market import sync_summary
from app.settings import SettingsRecord, load_settings, save_settings

__all__ = ["settings_router"]

logger = logging.getLogger(__name__)

settings_router = APIRouter(tags=["settings"])


@settings_router.get("/settings", response_model=SettingsResponse)
def get_settings_document() -> SettingsResponse:
    """当前设置：显示偏好、风险默认值、执行开关、数据源与密钥状态。"""

    return _response(load_settings())


@settings_router.patch("/settings", response_model=SettingsResponse)
def patch_settings_document(payload: SettingsUpdateRequest) -> SettingsResponse:
    """按分组部分更新；未提交的分组保持原值。"""

    _validate_macro(payload)
    record = save_settings(
        display=None if payload.display is None else payload.display.model_dump(mode="json"),
        risk_defaults=None
        if payload.risk_defaults is None
        else payload.risk_defaults.model_dump(mode="json"),
        execution=None if payload.execution is None else payload.execution.model_dump(mode="json"),
        data_sources=None
        if payload.data_sources is None
        else payload.data_sources.model_dump(exclude_unset=True),
        notifications=_notifications(payload),
        api_key=_api_key(payload),
    )
    if payload.notifications is not None and payload.notifications.channels is not None:
        apply_channels(record.notifications.get("channels", []))
    return _response(record)


@settings_router.post(
    "/settings/notifications/test",
    response_model=NotificationChannelTestResponse,
)
async def test_notification_channel(
    payload: NotificationChannelTestRequest,
) -> NotificationChannelTestResponse:
    """用同一个通道实现投一条测试事件，并把这次投递写进台账。"""

    sink = build_channel(payload.channel, config=_config_provider())
    if sink is None:
        raise HTTPException(status_code=404, detail=f"未实现的通道 {payload.channel}")
    try:
        result = await sink.deliver(_test_event())
    except Exception as exc:  # 通道自己抛错也要给出可读结果，不能让设置页 500
        logger.exception("测试发送失败: channel=%s", payload.channel)
        result = DeliveryResult(channel=payload.channel, status="failed", error=str(exc))
    await record_delivery(result)
    return NotificationChannelTestResponse(
        channel=result.channel,
        status=result.status,
        error=result.error,
    )


@settings_router.get(
    "/settings/notifications/deliveries",
    response_model=DeliveryListResponse,
)
def get_notification_deliveries(
    limit: int = Query(20, ge=1, le=100),
) -> DeliveryListResponse:
    """最近若干条投递记录，新的在前。"""

    return DeliveryListResponse(items=[_delivery(row) for row in list_deliveries(limit)])


def _notifications(payload: SettingsUpdateRequest) -> dict[str, Any] | None:
    """只提交出来的子项；未提交的子项在 `save_settings` 里保持原值。"""

    group = payload.notifications
    if group is None:
        return None
    values: dict[str, Any] = {}
    if group.channels is not None:
        values["channels"] = list(group.channels)
    if group.telegram is not None:
        values["telegram"] = {"chat_id": group.telegram.chat_id}
    if group.webhook is not None:
        values["webhook"] = {"url": group.webhook.url}
    return values


def _api_key(payload: SettingsUpdateRequest) -> str | None:
    if payload.exchange is None or payload.exchange.api_key is None:
        return None
    return payload.exchange.api_key.get_secret_value()


def _notification_settings(record: SettingsRecord) -> NotificationSettings:
    runtime = runtime_settings()
    telegram = record.notifications.get("telegram", {})
    webhook = record.notifications.get("webhook", {})
    return NotificationSettings(
        channels=[str(item) for item in record.notifications.get("channels", [])],
        telegram=TelegramSettings(
            chat_id=str(telegram.get("chat_id", "")),
            token_configured=bool(runtime.telegram_bot_token.strip()),
        ),
        webhook=WebhookSettings(
            url=str(webhook.get("url", "")),
            secret_configured=bool(runtime.webhook_signing_secret.strip()),
        ),
    )


def _config_provider() -> Callable[[], ChannelConfig]:
    """通道读取配置的入口：设置查询在投递时执行，由通道挪到线程里，不占事件循环。"""

    def provider() -> ChannelConfig:
        return _channel_config(load_settings())

    return provider


def _channel_config(record: SettingsRecord) -> ChannelConfig:
    """把设置文档与两份环境变量合成通道配置；敏感值只在这里读，不进响应。"""

    runtime = runtime_settings()
    return config_from_notifications(
        record.notifications,
        telegram_bot_token=runtime.telegram_bot_token,
        telegram_api_base=runtime.telegram_api_base,
        webhook_signing_secret=runtime.webhook_signing_secret,
    )


def _test_event() -> DomainEvent:
    """一条明确的测试告警：正文写清是测试，不冒充真实行情。"""

    moment = datetime.now(UTC).replace(microsecond=0)
    return DomainEvent(
        kind="alert",
        inst_id=None,
        payload={
            "rule_id": "settings_test",
            "alert": {
                "id": "al_settings_test",
                "type": "system",
                "severity": "info",
                "title": "测试消息",
                "detail": "来自设置页的测试发送，只用于确认通道是否可用。",
                "instrument_id": None,
                "triggered_at": moment.isoformat(),
            },
        },
        occurred_at=moment,
    )


def _validate_macro(payload: SettingsUpdateRequest) -> None:
    """写侧校验宏观分组的 provider 名；不合法当场 400，并列出该序列可选的值。

    契约层的 `Literal` 已经挡住未登记的名字；这里再按「序列」校验一次——同一个已登记的
    provider 未必适用于某个序列（例如国债只有财政部官方源）。校验推迟到读配置时，写入
    会先返回成功，之后首页整体报错、调度器每轮空转。
    """

    if payload.data_sources is None or payload.data_sources.macro is None:
        return
    series = payload.data_sources.macro.series or {}
    validate_series_override(
        {series_id: entry.model_dump(exclude_none=True) for series_id, entry in series.items()}
    )


def _macro_settings(record: SettingsRecord) -> MacroSettings:
    """宏观分组 → 契约模型；只暴露序列→provider 与调度周期，上游地址留在服务端。"""

    macro = record.data_sources.get("macro")
    macro = macro if isinstance(macro, dict) else {}
    raw_series = macro.get("series")
    raw_series = raw_series if isinstance(raw_series, dict) else {}
    series = {
        series_id: MacroSeriesSettings(
            minute=None if not isinstance(entry, dict) else entry.get("minute"),
            daily=None if not isinstance(entry, dict) else entry.get("daily"),
        )
        for series_id, entry in raw_series.items()
        if isinstance(series_id, str)
    }
    scheduler = macro.get("scheduler")
    interval = scheduler.get("minute") if isinstance(scheduler, dict) else None
    return MacroSettings(
        series=series,
        scheduler=MacroSchedulerSettings(minute=interval if isinstance(interval, str) else "1m"),
    )


def _delivery(row: NotificationDeliveryRow) -> DeliveryItem:
    return DeliveryItem(
        id=row.id,
        channel=row.channel,
        alert_id=row.alert_id,
        status=row.status,
        error=row.error,
        created_at=row.created_at,
    )


def _response(record: SettingsRecord) -> SettingsResponse:
    last_sync_at, failure_count = sync_summary(OKX_PROVIDER)
    return SettingsResponse(
        display=DisplaySettings(**record.display),
        risk_defaults=RiskDefaults(**record.risk_defaults),
        execution=ExecutionSettings(**record.execution),
        data_sources=DataSourceSettings(
            subscribed_instruments=list(record.data_sources.get("subscribed_instruments", [])),
            last_sync_at=last_sync_at,
            failure_count=failure_count,
            macro=_macro_settings(record),
        ),
        notifications=_notification_settings(record),
        secrets=SecretSettings(
            okx_api_key_masked=record.api_key_masked,
            okx_configured=record.api_configured,
            okx_permission="unknown" if record.api_configured else None,
        ),
        updated_at=record.updated_at,
    )

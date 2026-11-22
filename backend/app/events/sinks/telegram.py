"""Telegram 通道：把告警发到一个聊天里。

只用纯文本，不用 Markdown：转义规则随版本变化，一条报警不该因为标题里有个下划线就发
不出去。正文四行——级别与标题、详情、标的、发生时刻——与浏览器通道展示的是同一份事实。

bot token 只从环境变量 `TELEGRAM_BOT_TOKEN` 读，接口地址只从配置读
（`TELEGRAM_API_BASE`），两者都只出现在请求地址里；失败原因由
`http` 模块统一措辞，永不包含地址，所以令牌不会进投递台账、日志或接口响应。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx

from app.events.event import DomainEvent
from app.events.sinks.base import DeliveryResult, alert_payload, utc_moment
from app.events.sinks.config import ChannelConfig
from app.events.sinks.http import Sleep, post_json

__all__ = ["TelegramSink"]


class TelegramSink:
    """`POST /bot<token>/sendMessage`；token 与 chat_id 都在每次投递时现读。"""

    name = "telegram"

    def __init__(
        self,
        config: Callable[[], ChannelConfig],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._config = config
        self._transport = transport
        self._sleep = sleep

    def accepts(self, event: DomainEvent) -> bool:
        return alert_payload(event) is not None

    async def deliver(self, event: DomainEvent) -> DeliveryResult:
        alert = alert_payload(event)
        if alert is None:
            return DeliveryResult(self.name, "failed", "不是告警事件，没有可投递的正文")
        # 配置来自设置表的同步查询：挪到线程里，别占住事件循环。
        config = await asyncio.to_thread(self._config)
        missing = _missing(config)
        if missing:
            return DeliveryResult(self.name, "failed", "未配置：" + "；".join(missing))
        body = json.dumps(
            {
                "chat_id": config.telegram_chat_id,
                "text": _text(event, alert),
                "disable_web_page_preview": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        url = f"{config.telegram_api_base}/bot{config.telegram_bot_token}/sendMessage"
        error = await post_json(
            url,
            content=body,
            headers={"Content-Type": "application/json"},
            transport=self._transport,
            sleep=self._sleep,
        )
        if error is not None:
            return DeliveryResult(self.name, "failed", error)
        return DeliveryResult(self.name, "delivered")


def _missing(config: ChannelConfig) -> list[str]:
    """缺哪一项就写哪一项：chat_id 是用户能在设置页填的，token 只能由环境变量注入。"""

    missing: list[str] = []
    if not config.telegram_chat_id:
        missing.append("请先在设置页填写 Telegram chat_id")
    if not config.telegram_bot_token:
        missing.append("需要注入 TELEGRAM_BOT_TOKEN 环境变量")
    if not config.telegram_api_base:
        missing.append("需要配置 TELEGRAM_API_BASE")
    return missing


def _text(event: DomainEvent, alert: dict[str, object]) -> str:
    """四行纯文本：`[{severity}] {title}` / 详情 / 标的 / 时间。"""

    severity = _field(alert, "severity") or "unknown"
    title = _field(alert, "title") or "告警"
    detail = _field(alert, "detail") or "无详情"
    instrument = _field(alert, "instrument_id") or event.inst_id or "未指定"
    return "\n".join(
        (
            f"[{severity}] {title}",
            detail,
            f"标的：{instrument}",
            f"时间：{utc_moment(event.occurred_at)}",
        )
    )


def _field(alert: dict[str, object], key: str) -> str:
    value = alert.get(key)
    return str(value).strip() if isinstance(value, str | int | float) else ""

"""Telegram 通道：把告警发到一个聊天里。

只用纯文本，不用 Markdown：转义规则随版本变化，一条报警不该因为标题里有个下划线就发
不出去。正文由 `render.render_message` 统一渲染，与浏览器通道、Webhook 推送的是同一段
文字；超过 Telegram 的上限时由渲染侧截断明细，标的时间保留。

bot token 只从环境变量 `TELEGRAM_BOT_TOKEN` 读，接口地址只从配置读
（`TELEGRAM_API_BASE`），两者都只出现在请求地址里；失败原因由
`http` 模块统一措辞，永不包含地址，所以令牌不会进投递台账、日志或接口响应。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx

from app.events.sinks.base import DeliveryResult
from app.events.sinks.config import ChannelConfig
from app.events.sinks.digest import DeliveryDigest
from app.events.sinks.http import Sleep, post_json
from app.events.sinks.render import render_message

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

    async def deliver(self, digest: DeliveryDigest) -> DeliveryResult:
        # 配置来自设置表的同步查询：挪到线程里，别占住事件循环。
        config = await asyncio.to_thread(self._config)
        missing = _missing(config)
        if missing:
            return DeliveryResult(self.name, "failed", "未配置：" + "；".join(missing))
        body = json.dumps(
            {
                "chat_id": config.telegram_chat_id,
                "text": render_message(digest),
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

"""通道的运行期配置：非敏感值来自设置文档，敏感值只来自环境变量。

Telegram 的 `chat_id` 与 Webhook 的接收地址是可编辑的非敏感值，存在设置文档的
`notifications` 分组里；`TELEGRAM_BOT_TOKEN` 与 `WEBHOOK_SIGNING_SECRET` 只从环境变量
注入，既不落库也不经 HTTP 回显（与交易所 Secret 的约定一致）。

配置在**每次投递时**读取，所以设置页保存后立即生效，不需要重启进程。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = ["ChannelConfig", "config_from_notifications"]


@dataclass(frozen=True, slots=True)
class ChannelConfig:
    """两个通道合起来的一份配置；缺项为空字符串，表示「未配置」。"""

    telegram_chat_id: str = ""
    telegram_bot_token: str = ""
    telegram_api_base: str = ""
    webhook_url: str = ""
    webhook_signing_secret: str = ""


def config_from_notifications(
    notifications: Mapping[str, Any],
    *,
    telegram_bot_token: str = "",
    telegram_api_base: str = "",
    webhook_signing_secret: str = "",
) -> ChannelConfig:
    """把设置文档的 `notifications` 分组与三份环境变量合成一份通道配置。"""

    return ChannelConfig(
        telegram_chat_id=_text(notifications.get("telegram"), "chat_id"),
        telegram_bot_token=telegram_bot_token.strip(),
        telegram_api_base=telegram_api_base.strip(),
        webhook_url=_text(notifications.get("webhook"), "url"),
        webhook_signing_secret=webhook_signing_secret.strip(),
    )


def _text(group: Any, key: str) -> str:
    if not isinstance(group, Mapping):
        return ""
    value = group.get(key)
    return value.strip() if isinstance(value, str) else ""

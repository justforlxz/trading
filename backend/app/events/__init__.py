"""事件驱动通知：上游推送 → 中间件管线 → 投递通道。

跨包只允许 `from app.events import ...`，且只发布下面这些：

- `DomainEvent`：事件的形状，推送层构造它；
- `emit`：全项目唯一的事件入口；
- `install` / `uninstall`：装配根安装与卸载管线；
- `build_pipeline` / `build_sinks`：按注册表组装链路与通道；
- `apply_channels`：通道开关变化时立即生效，不用重启进程；
- `DeliveryDigest` / `digest_of` / `render_message`：一次投递的内容与全项目唯一的渲染
  入口，三个通道共用；
- `DEFAULT_SUBSCRIPTIONS` / `resolve_subscriptions`：按通道的类型订阅与最低严重度，
  未配置时按默认值运行。

扩展点只有两个注册表：`app.events.pipeline.DEFAULT_MIDDLEWARES`（新增规则或处理）
与 `app.events.sinks.registry.CHANNEL_BUILDERS`（新增通道）。两者都不需要改
`stream/hub.py` 或 `alerts/`。

外部通道（`telegram` / `webhook`）的地址与凭据由装配根合成为 `ChannelConfig` 注入；
设置页的「测试发送」用 `build_channel` 单独构造一个通道，「最近投递」用
`list_deliveries` 读同一张台账。
"""

from app.events.bus import apply_channels, emit, install, uninstall
from app.events.event import DomainEvent
from app.events.pipeline import build_pipeline
from app.events.sinks.base import DeliveryResult, NotificationDeliveryRow
from app.events.sinks.config import ChannelConfig, config_from_notifications
from app.events.sinks.digest import DeliveryDigest, DigestItem, digest_of
from app.events.sinks.registry import (
    build_channel,
    build_sinks,
    list_deliveries,
    record_delivery,
)
from app.events.sinks.render import render_message
from app.events.sinks.subscriptions import DEFAULT_SUBSCRIPTIONS, resolve_subscriptions

__all__ = [
    "DEFAULT_SUBSCRIPTIONS",
    "ChannelConfig",
    "DeliveryDigest",
    "DeliveryResult",
    "DigestItem",
    "DomainEvent",
    "NotificationDeliveryRow",
    "apply_channels",
    "build_channel",
    "build_pipeline",
    "build_sinks",
    "config_from_notifications",
    "digest_of",
    "emit",
    "install",
    "list_deliveries",
    "record_delivery",
    "render_message",
    "resolve_subscriptions",
    "uninstall",
]

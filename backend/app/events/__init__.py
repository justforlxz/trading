"""事件驱动通知：上游推送 → 中间件管线 → 投递通道。

跨包只允许 `from app.events import ...`，且只发布四样东西：

- `DomainEvent`：事件的形状，推送层构造它；
- `emit`：全项目唯一的事件入口；
- `install` / `uninstall`：装配根安装与卸载管线；
- `build_pipeline` / `build_sinks`：按注册表组装链路与通道；
- `apply_channels`：通道开关变化时立即生效，不用重启进程。

扩展点只有两个注册表：`app.events.pipeline.DEFAULT_MIDDLEWARES`（新增规则或处理）
与 `app.events.sinks.registry.CHANNEL_BUILDERS`（新增通道）。两者都不需要改
`stream/hub.py` 或 `alerts/`。
"""

from app.events.bus import apply_channels, emit, install, uninstall
from app.events.event import DomainEvent
from app.events.pipeline import build_pipeline
from app.events.sinks.base import NotificationDeliveryRow
from app.events.sinks.registry import build_sinks

__all__ = [
    "DomainEvent",
    "NotificationDeliveryRow",
    "apply_channels",
    "build_pipeline",
    "build_sinks",
    "emit",
    "install",
    "uninstall",
]

"""浏览器通道：把告警推给订阅了 `alerts` 的浏览器连接。

推送走的还是现有那条 WS：`broadcast` 由装配根注入，实现是 `StreamHub.publish`，
带一个只看 `client.alerts` 的过滤条件——没订阅告警的页面不会收到，行情与账户推送
也不受影响。

浏览器通知本身的权限与展示在前端（`frontend/src/lib/notifications.ts`）：Notification
API 只能由页面调用，服务端无法替用户授权，也无法在页面关闭后弹窗。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.events.event import DomainEvent
from app.events.sinks.base import DeliveryResult

__all__ = ["BrowserSink"]

logger = logging.getLogger(__name__)

#: `(事件类型, 数据, 发生时刻, 只有它返回 True 的连接才收)`。
Broadcast = Callable[..., None]


def _wants_alerts(client: Any) -> bool:
    return bool(getattr(client, "alerts", False))


class BrowserSink:
    """把 `alert` 事件广播成 `alert.created`；载荷与提醒接口的条目一致。"""

    name = "browser"

    def __init__(self, broadcast: Broadcast) -> None:
        self._broadcast = broadcast

    def accepts(self, event: DomainEvent) -> bool:
        return event.kind == "alert" and isinstance(event.payload.get("alert"), dict)

    async def deliver(self, event: DomainEvent) -> DeliveryResult:
        alert = dict(event.payload["alert"])
        try:
            self._broadcast(
                "alert.created",
                alert,
                event.occurred_at,
                _wants_alerts,
            )
        except Exception as exc:  # 推送失败要留在台账里，不能静默
            logger.exception("浏览器通道投递失败: alert=%s", alert.get("id"))
            return DeliveryResult(channel=self.name, status="failed", error=str(exc))
        return DeliveryResult(channel=self.name, status="delivered")

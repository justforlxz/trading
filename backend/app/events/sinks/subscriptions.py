"""按通道的订阅：收哪几类提醒、最低到什么严重程度才收。

订阅写在设置文档的 `notifications.subscriptions` 里，形状是「通道 → 类型清单 + 最低
严重度」。没有配置的通道、没有配置的项一律回落到下面的默认值，因此老配置不需要迁移：

- Telegram 只收持仓风险与策略信号，且警告以上——现在绝大多数提醒是提示级技术形态；
- 浏览器全收：它只在页面打开时存在，用户本来就在看；
- Webhook 默认为空：接收方是用户自己的服务，先不推任何类型，需要什么再勾。

过滤发生在投递之前，被挡下的提醒不写投递台账：台账只记真实投递，否则以后排查
「为什么这一小时只收到两条」会被未投递记录污染。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.alerts import ALERT_SEVERITIES, ALERT_TYPES

__all__ = [
    "DEFAULT_SUBSCRIPTIONS",
    "SEVERITY_ORDER",
    "ChannelSubscription",
    "resolve_subscriptions",
]

#: 严重度的高低顺序：数字越大越严重。
SEVERITY_ORDER: dict[str, int] = {"info": 0, "warning": 1, "critical": 2}

#: 三个通道的默认订阅；未配置时按这份运行。
DEFAULT_SUBSCRIPTIONS: dict[str, dict[str, Any]] = {
    "telegram": {"types": ["risk", "strategy"], "min_severity": "warning"},
    "browser": {"types": list(ALERT_TYPES), "min_severity": "info"},
    "webhook": {"types": [], "min_severity": "warning"},
}


@dataclass(frozen=True, slots=True)
class ChannelSubscription:
    """一个通道的生效订阅：只投递清单里的类型，且不低于最低严重度。"""

    types: tuple[str, ...]
    min_severity: str

    def allows(self, alert: Mapping[str, Any]) -> bool:
        kind = alert.get("type")
        if not isinstance(kind, str) or kind not in self.types:
            return False
        return severity_rank(alert.get("severity")) >= SEVERITY_ORDER[self.min_severity]


def severity_rank(value: object) -> int:
    """未知严重度按最低处理：宁可漏报一条，也不把没登记的级别当成紧急推出去。"""

    return SEVERITY_ORDER.get(value, -1) if isinstance(value, str) else -1


def resolve_subscriptions(value: Mapping[str, Any] | None) -> dict[str, ChannelSubscription]:
    """设置文档里的订阅 → 每个通道的生效订阅；缺项按默认值补齐。"""

    stored = value if isinstance(value, Mapping) else {}
    return {
        channel: ChannelSubscription(
            types=_types(stored.get(channel), defaults["types"]),
            min_severity=_severity(stored.get(channel), defaults["min_severity"]),
        )
        for channel, defaults in DEFAULT_SUBSCRIPTIONS.items()
    }


def _types(entry: Any, default: list[str]) -> tuple[str, ...]:
    if not isinstance(entry, Mapping):
        return tuple(default)
    values = entry.get("types")
    if not isinstance(values, list):
        return tuple(default)
    known = [item.strip() for item in values if isinstance(item, str) and item.strip()]
    return tuple(dict.fromkeys(item for item in known if item in ALERT_TYPES))


def _severity(entry: Any, default: str) -> str:
    if not isinstance(entry, Mapping):
        return default
    value = entry.get("min_severity")
    return value if isinstance(value, str) and value in ALERT_SEVERITIES else default

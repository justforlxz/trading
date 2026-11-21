"""领域事件的形状：只带最小字段，富化放在中间件里。

本模块不决定事件从哪来、往哪去。上游推送落到 `StreamHub` 之后由它构造一条
`DomainEvent` 交给 `emit`；中间件在链路上补充字段、判定规则、过滤投递。

事件种类只登记当前真的有产出方的四种：`quote` / `account` / `position` 由推送层
产出，`alert` 由 `rule_engine` 中间件产出。`candle` 故意不登记：公共 WS 目前没有
订阅 candle 频道（`DEFAULT_PUBLIC_CHANNELS` 只有 tickers / mark-price /
index-tickers），没有事件源就没有事件类型；接入 candle 订阅后在这里补一个 `candle`
种类，并在 `rule_engine` 里接上对应规则，不需要定时器凑。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Literal

__all__ = ["DomainEvent", "EventKind"]

EventKind = Literal["quote", "account", "position", "alert"]


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """一条待处理的事实：种类、标的、载荷与发生时刻。

    `payload` 只放这条事实本身已有的数值；任何派生值（指标、规则判定结果、告警
    正文）都在中间件里产生，不在这里预先算好。
    """

    kind: EventKind
    inst_id: str | None
    payload: Mapping[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        if self.occurred_at.tzinfo is None:
            raise ValueError("事件的 occurred_at 必须带时区")

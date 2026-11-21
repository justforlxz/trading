"""领域事件的形状：只带最小字段，富化放在中间件里。

本模块不决定事件从哪来、往哪去。上游推送落到 `StreamHub` 之后由它构造一条
`DomainEvent` 交给 `emit`；中间件在链路上补充字段、判定规则、过滤投递。K 线与行情
来自两个上游连接（`ws/v5/public` 与 `ws/v5/business`），但落到同一条队列、同一条管线。

事件种类只登记当前真的有产出方的五种：`quote` / `account` / `position` /
`candle.closed` 由推送层产出，`alert` 由 `rule_engine` 与 `technical` 中间件产出。
K 线只在**确认收盘**（上游 `confirm=1`）时产生 `candle.closed`；未收盘的推送在推送层
就被丢弃，不进队列，因此下游不需要再判一次收没收盘。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Literal

__all__ = ["DomainEvent", "EventKind"]

EventKind = Literal["quote", "account", "position", "alert", "candle.closed"]


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

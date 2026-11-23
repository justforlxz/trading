"""一次投递的内容：同一轮评估产出的告警按「标的 + 类型」合并后的条目。

一轮评估指一次 `Pipeline.run`：一条行情或一根收盘 K 线穿过管线，途中产出的全部告警
属于同一轮。同一轮里同 `(标的, 类型)` 的多条告警合并成一条，条数记在 `count` 里；
三个通道拿到的都是这份内容，因此正文天然一致。

跨轮降频由 `MergeWindow` 负责：同一 `(通道, 标的, 类型)` 在窗口内只投递一次，窗口内
被挡下的条数累计下来，并进该键下一次投递的 `count`。窗口状态只在进程内存里，重启
后清空——与管线其它内存状态（规则跃迁、去重）同一约定，不落库、不加定时器。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from app.events.event import DomainEvent
from app.events.sinks.base import alert_payload

__all__ = [
    "DEFAULT_MERGE_WINDOW",
    "MAX_SUMMARY_ITEMS",
    "DeliveryDigest",
    "DigestItem",
    "MergeWindow",
    "digest_of",
    "group_digest",
]

#: 合并窗口：同一 (通道, 标的, 类型) 在 10 分钟内只投递一次。
DEFAULT_MERGE_WINDOW = timedelta(minutes=10)
#: 摘要里最多列几条明细，余下的只体现在首行的计数里。
MAX_SUMMARY_ITEMS = 5


@dataclass(frozen=True, slots=True)
class DigestItem:
    """一条投递内容：一条告警，以及它在同一轮里被合并的次数。

    单条自己的时刻不单独保存：正文与合并窗口都用整轮的 `DeliveryDigest.occurred_at`，
    多存一份会让人误以为存在「这一条的时间」语义。
    """

    alert: Mapping[str, Any]
    count: int = 1

    @property
    def id(self) -> str | None:
        value = self.alert.get("id")
        return value if isinstance(value, str) else None

    @property
    def type(self) -> str:
        return _text(self.alert.get("type"))

    @property
    def instrument_id(self) -> str:
        return _text(self.alert.get("instrument_id"))


@dataclass(frozen=True, slots=True)
class DeliveryDigest:
    """一次投递的全部内容；`occurred_at` 是这一轮的时刻。"""

    items: tuple[DigestItem, ...]
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError("一次投递至少要有一条内容")

    @property
    def total(self) -> int:
        """这一轮真正产出的告警条数（含被合并与窗口内被挡下的）。"""

        return sum(item.count for item in self.items)

    @property
    def alert(self) -> Mapping[str, Any]:
        """首条告警：送给浏览器与 Webhook 的结构化字段仍取自这一条。"""

        return self.items[0].alert

    def type_counts(self) -> tuple[tuple[str, int], ...]:
        """按首次出现的顺序给出类型分布：`(类型, 条数)`。"""

        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.type] = counts.get(item.type, 0) + item.count
        return tuple(counts.items())


def digest_of(event: DomainEvent) -> DeliveryDigest | None:
    """单条事件 → 一次投递内容；不是告警事件时返回 `None`（测试发送也走这里）。"""

    return group_digest([event])


def group_digest(events: Iterable[DomainEvent]) -> DeliveryDigest | None:
    """把一轮里的告警事件按 `(标的, 类型)` 合并；一条都没有时返回 `None`。"""

    items: list[DigestItem] = []
    positions: dict[tuple[str, str], int] = {}
    moment: datetime | None = None
    for event in events:
        alert = alert_payload(event)
        if alert is None:
            continue
        moment = event.occurred_at if moment is None else max(moment, event.occurred_at)
        key = (_text(alert.get("instrument_id")), _text(alert.get("type")))
        position = positions.get(key)
        if position is None:
            positions[key] = len(items)
            items.append(DigestItem(alert=alert))
            continue
        existing = items[position]
        items[position] = replace(existing, count=existing.count + 1)
    if moment is None:
        return None
    return DeliveryDigest(items=tuple(items), occurred_at=moment)


@dataclass(slots=True)
class MergeWindow:
    """合并窗口：同一键在窗口内只放行一次，挡下的条数并入下一次放行。"""

    window: timedelta = DEFAULT_MERGE_WINDOW
    #: 键 → 上一次投递的时刻。
    last: dict[tuple[str, str, str], datetime] = field(default_factory=dict)
    #: 键 → 窗口内被挡下的条数。
    suppressed: dict[tuple[str, str, str], int] = field(default_factory=dict)

    def admit(self, key: tuple[str, str, str], count: int, moment: datetime) -> int | None:
        """放行时返回本次要投递的条数（含此前挡下的），不放行时返回 `None`。"""

        previous = self.last.get(key)
        if previous is not None and moment - previous < self.window:
            self.suppressed[key] = self.suppressed.get(key, 0) + count
            return None
        pending = self.suppressed.pop(key, 0)
        self.last[key] = moment
        return count + pending


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""

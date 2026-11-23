"""一次投递的正文：全项目唯一的渲染入口。

三个通道（浏览器、Telegram、Webhook）拿到同一份 `DeliveryDigest`，都调用本模块的
`render_message`，因此同一输入在三个地方看到的正文逐字相同。通道自己只负责运输，
不拼文案、不改字段。

单条告警按四行固定结构渲染，缺值的整行省掉，不留 `None` 与空行：

    {icon} {type_label} · {severity_label}
    {instrument_id}  {price}  {change_pct}
    {detail}
    {time}

单条结构里不出现标题：规则产出的详情已经带着标的与数值（例如「收盘价 101 跌破
MA20（102）」），标题只是同一件事的短名，重复一遍只会让通知变长。摘要的明细行才用
标题——那一行没有详情，标题是唯一能区分条目的文字。

同一轮产出的多条（或同一轮里被合并的多次）换成摘要：首行是条数与类型分布，其下
最多列 `MAX_SUMMARY_ITEMS` 条明细，单条明细在合并多次时带 `×N`。

正文超过 `MESSAGE_LIMIT` 时只截断明细/说明那一行并追加 `…`，标的与时间不截断：
时间是判断这条通知是否过期的唯一依据，标的是跳转过去看详情的入口。
"""

from __future__ import annotations

from typing import Any

from app.events.sinks.base import utc_moment
from app.events.sinks.digest import MAX_SUMMARY_ITEMS, DeliveryDigest, DigestItem

__all__ = [
    "MESSAGE_LIMIT",
    "SEVERITY_ICONS",
    "SEVERITY_LABELS",
    "SUMMARY_ICON",
    "TYPE_LABELS",
    "message_width",
    "render_message",
    "severity_label",
    "type_label",
]

#: Telegram 的单条消息上限；三个通道共用，保证「同一输入三种输出一致」。
MESSAGE_LIMIT = 4096

#: 提醒类型的中文标签；未登记的类型原样显示，不伪造解释。
#: `system` 只用于设置页的「测试发送」：那条告警是合成的，不属于任何规则。
TYPE_LABELS: dict[str, str] = {
    "indicator": "技术形态",
    "price": "价格区间",
    "risk": "持仓风险",
    "strategy": "策略信号",
    "data": "数据缺口",
    "system": "系统",
}

SEVERITY_LABELS: dict[str, str] = {
    "info": "提示",
    "warning": "警告",
    "critical": "紧急",
}

SEVERITY_ICONS: dict[str, str] = {
    "info": "🔔",
    "warning": "⚠️",
    "critical": "🚨",
}

#: 摘要首行的图标：与单条的严重度图标区分开，一眼看出这是合并后的一条。
SUMMARY_ICON = "📊"


def type_label(value: str) -> str:
    return TYPE_LABELS.get(value, value)


def severity_label(value: str) -> str:
    return SEVERITY_LABELS.get(value, value)


def message_width(text: str) -> int:
    """按 UTF-16 码元计长度：Telegram 的上限按这个单位算，emoji 占两个。"""

    return len(text.encode("utf-16-le")) // 2


def render_message(digest: DeliveryDigest, *, limit: int = MESSAGE_LIMIT) -> str:
    """渲染一次投递的正文；超过 `limit` 时截断明细并追加 `…`。"""

    lines, truncatable = _lines(digest)
    text = "\n".join(lines)
    if message_width(text) <= limit:
        return text
    overflow = message_width(text) - limit
    if truncatable is not None:
        line = lines[truncatable]
        lines[truncatable] = _shorten(line, overflow, limit)
        text = "\n".join(lines)
    if message_width(text) > limit:  # 兜底：非明细部分本身就超长，只能整条截断
        text = _cut_to_limit(text, limit)
    return text


def _lines(digest: DeliveryDigest) -> tuple[list[str], int | None]:
    """正文各行，以及可以截断的那一行的下标。"""

    if digest.total == 1:
        return _single_lines(digest)
    return _summary_lines(digest)


def _single_lines(digest: DeliveryDigest) -> tuple[list[str], int | None]:
    alert = digest.alert
    severity = _text(alert.get("severity"))
    header = f"{SEVERITY_ICONS.get(severity, SEVERITY_ICONS['info'])} "
    header += f"{type_label(_text(alert.get('type')))} · {severity_label(severity)}"

    instrument = _text(alert.get("instrument_id"))
    price = _text(alert.get("price"))
    change = _text(alert.get("change_pct"))
    # 价格行三值齐全才出现：缺价格时这一行整行省掉，不留半截数字。
    meta = f"{instrument}  {price}  {change}" if instrument and price and change else ""

    detail = _text(alert.get("detail"))
    lines = [line for line in (header, meta, detail) if line]
    detail_index = len(lines) - 1 if detail else None
    lines.append(utc_moment(digest.occurred_at))
    return lines, detail_index


def _summary_lines(digest: DeliveryDigest) -> tuple[list[str], int | None]:
    counts = " · ".join(f"{type_label(name)} {count}" for name, count in digest.type_counts())
    lines = [f"{SUMMARY_ICON} 本轮 {digest.total} 条：{counts}"]
    for item in digest.items[:MAX_SUMMARY_ITEMS]:
        lines.append(_summary_item(item))
    lines.append(utc_moment(digest.occurred_at))
    # 明细行整体可截断：先压掉最后一条明细的文字，而不是动标的时间。
    detail_index = len(lines) - 2 if len(lines) > 2 else None
    return lines, detail_index


def _summary_item(item: DigestItem) -> str:
    alert = item.alert
    severity = _text(alert.get("severity"))
    icon = SEVERITY_ICONS.get(severity, SEVERITY_ICONS["info"])
    title = _text(alert.get("title")) or type_label(item.type)
    parts = [f"- {icon} {title}"]
    if item.instrument_id:
        parts.append(item.instrument_id)
    if item.count > 1:
        parts.append(f"×{item.count}")
    return "  ".join(parts)


def _shorten(line: str, overflow: int, limit: int) -> str:
    return _truncate(line, max(message_width(line) - overflow - 1, 1)) + "…"


def _cut_to_limit(text: str, limit: int) -> str:
    return _truncate(text, limit - 1) + "…"


def _truncate(text: str, width: int) -> str:
    """按 UTF-16 码元宽度截断；每个字符只量一次，不在前缀上反复重算。"""

    kept = 0
    for index, char in enumerate(text):
        kept += len(char.encode("utf-16-le")) // 2
        if kept > width:
            return text[:index]
    return text


def _text(value: Any) -> str:
    if isinstance(value, str | int | float):
        return str(value).strip()
    return ""

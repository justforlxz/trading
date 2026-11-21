"""统一事件形状：补齐并校验中间件要依赖的那几个字段。

推送给到的是上游原始解析结果，`normalize` 把它收紧成链路稳定依赖的形状：
`inst_id` 去空白、`payload` 一定是字典、`occurred_at` 一定带时区。缺少这些字段的
事件没有可靠的后续处理，直接中止链路（不调用 `call_next`），不猜值。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.events.event import DomainEvent

if TYPE_CHECKING:
    from app.events.pipeline import CallNext, Middleware, PipelineDeps

__all__ = ["middleware"]


def middleware(_deps: PipelineDeps) -> Middleware:
    async def normalize(event: DomainEvent, call_next: CallNext) -> None:
        inst_id = None if event.inst_id is None else event.inst_id.strip()
        if event.kind in {"quote", "account", "position", "alert"} and not event.payload:
            return
        if inst_id is not None and not inst_id:
            return
        await call_next(
            DomainEvent(
                kind=event.kind,
                inst_id=inst_id,
                payload=event.payload,
                occurred_at=event.occurred_at,
            )
        )

    return normalize

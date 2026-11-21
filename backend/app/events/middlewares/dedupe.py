"""去重：同一 (标的, 规则) 只在状态跃迁时放行。

规则状态机已经保证「一直越界只报一次」，这一层是第二道网：同一标的的同一规则如果
因为别的原因连续产出同一状态（例如多个规则来源给出相同结论），只放行第一次；状态
从「触发」回到「恢复」时放行一次，之后再次触发再放行。

状态只在内存里，且只按 `(标的, 规则)` 记录，规模由关注列表决定；进程重启后清空。
事件没有 `rule_id`（行情、账户、持仓）时不属于告警，本层不做判断，直接放行。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.events.event import DomainEvent

if TYPE_CHECKING:
    from app.events.pipeline import CallNext, Middleware, PipelineDeps

__all__ = ["middleware"]


def middleware(_deps: PipelineDeps) -> Middleware:
    # `(标的, 规则) -> 上一次放行的状态`
    last_state: dict[tuple[str, str], str] = {}

    async def dedupe(event: DomainEvent, call_next: CallNext) -> None:
        rule_id = event.payload.get("rule_id")
        state = event.payload.get("state")
        if not isinstance(rule_id, str) or not isinstance(state, str):
            await call_next(event)
            return
        key = (event.inst_id or "", rule_id)
        if last_state.get(key) == state:
            return
        last_state[key] = state
        await call_next(event)

    return dedupe

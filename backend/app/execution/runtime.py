"""自动执行的运行控制：默认关闭，显式开启，可暂停与恢复。

## 三个状态

    stopped ──enable──▶ running ──pause──▶ paused
       ▲                  │                 │
       └──────disable─────┴─────resume──────┘

- **stopped**：默认状态。没有显式开启时，自动执行循环连求差都不做，不会产生订单。
- **running**：允许循环按目标组合求差并下单。
- **paused**：全局暂停。下一轮不产生新订单，已有持仓保持不动；恢复后继续。

每次状态变化都记一条 `RuntimeEvent`，带发生时刻、动作、前后状态与操作人。没有变化
的调用不记录（重复点「开启」不会造出一串空事件）。

这是进程内控制，不是持久化开关：进程重启后回到 `stopped`，必须重新显式开启。把
「重启后仍然自动交易」当成默认行为，会在无人值守时放大风险。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core import Clock, SystemClock, ValidationError

__all__ = [
    "ACTION_DISABLE",
    "ACTION_ENABLE",
    "ACTION_PAUSE",
    "ACTION_RESUME",
    "RUNTIME_PAUSED",
    "RUNTIME_RUNNING",
    "RUNTIME_STOPPED",
    "AutoRuntime",
    "RuntimeEvent",
]

RUNTIME_STOPPED = "stopped"
RUNTIME_RUNNING = "running"
RUNTIME_PAUSED = "paused"

ACTION_ENABLE = "enable"
ACTION_DISABLE = "disable"
ACTION_PAUSE = "pause"
ACTION_RESUME = "resume"

_ACTIONS = frozenset({ACTION_ENABLE, ACTION_DISABLE, ACTION_PAUSE, ACTION_RESUME})


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """一次运行状态变化。`previous` 与 `current` 必然不同。"""

    at: datetime
    action: str
    previous: str
    current: str
    actor: str

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValidationError("运行状态变化的时刻必须带时区")
        if self.action not in _ACTIONS:
            raise ValidationError(f"未知的运行控制动作 {self.action!r}")
        if self.previous == self.current:
            raise ValidationError("运行状态变化的前后状态不能相同")
        if not isinstance(self.actor, str) or not self.actor.strip():
            raise ValidationError("运行状态变化必须记录操作人")


class AutoRuntime:
    """自动执行循环的启停与暂停开关。"""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._state = RUNTIME_STOPPED
        self._events: list[RuntimeEvent] = []

    @property
    def state(self) -> str:
        """当前状态：`stopped` / `running` / `paused`。"""

        return self._state

    @property
    def events(self) -> tuple[RuntimeEvent, ...]:
        """按时间顺序记录的状态变化。"""

        return tuple(self._events)

    @property
    def can_trade(self) -> bool:
        """只有 `running` 状态允许产生新订单。"""

        return self._state == RUNTIME_RUNNING

    def enable(self, *, actor: str = "system") -> RuntimeEvent | None:
        """从关闭状态显式开启；已经开启时不做任何事。"""

        return self._move(ACTION_ENABLE, RUNTIME_RUNNING, actor=actor, allowed={RUNTIME_STOPPED})

    def disable(self, *, actor: str = "system") -> RuntimeEvent | None:
        """关闭自动执行；运行中与暂停中都回到关闭状态。"""

        return self._move(
            ACTION_DISABLE,
            RUNTIME_STOPPED,
            actor=actor,
            allowed={RUNTIME_RUNNING, RUNTIME_PAUSED},
        )

    def pause(self, *, actor: str = "system") -> RuntimeEvent | None:
        """暂停运行中的循环；关闭状态没有可暂停的东西。"""

        return self._move(ACTION_PAUSE, RUNTIME_PAUSED, actor=actor, allowed={RUNTIME_RUNNING})

    def resume(self, *, actor: str = "system") -> RuntimeEvent | None:
        """从暂停恢复运行；关闭状态必须先显式开启。"""

        return self._move(ACTION_RESUME, RUNTIME_RUNNING, actor=actor, allowed={RUNTIME_PAUSED})

    def _move(
        self,
        action: str,
        target: str,
        *,
        actor: str,
        allowed: set[str],
    ) -> RuntimeEvent | None:
        if self._state not in allowed:
            return None
        if not isinstance(actor, str) or not actor.strip():
            raise ValidationError("运行控制必须记录操作人")
        event = RuntimeEvent(
            at=self._clock.now(),
            action=action,
            previous=self._state,
            current=target,
            actor=actor,
        )
        self._state = target
        self._events.append(event)
        return event

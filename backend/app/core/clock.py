"""时间来源抽象。

业务代码不直接调用 `datetime.now()`：回测要把「现在」钉在历史某个时刻，实盘要走
系统时钟。两者只对调用方暴露 `now()`，拿不到「快进」能力——推进时间只能由回放引擎
通过 `ReplayClock.advance_to` 完成。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from app.core.errors import ValidationError

__all__ = ["Clock", "ReplayClock", "SystemClock", "utc_from_millis"]


@runtime_checkable
class Clock(Protocol):
    """时钟端口：任何返回「当前时刻」的实现都必须带时区。"""

    def now(self) -> datetime:
        """当前时刻（带时区）。"""

        raise NotImplementedError


class SystemClock:
    """实盘时钟：返回 UTC 当前时刻。"""

    def now(self) -> datetime:
        return datetime.now(UTC)


class ReplayClock:
    """回测时钟：初始时刻固定，只能由回放引擎向前推进。

    时间单调前进，倒退会破坏「先有因后有果」的假设（例如先看到了收盘价再下单），
    因此逆序推进直接报错而不是悄悄接受。
    """

    def __init__(self, start: datetime) -> None:
        _require_aware(start, "start")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance_to(self, ts: datetime) -> None:
        """把当前时刻推进到 `ts`（允许原地不动，不允许倒退）。"""

        _require_aware(ts, "ts")
        if ts < self._now:
            raise ValidationError(
                f"回放时钟不能倒退: {ts.isoformat()} 早于 {self._now.isoformat()}"
            )
        self._now = ts


def utc_from_millis(value: str | int) -> datetime:
    """毫秒时间戳 → 带时区的 UTC 时间。

    上游普遍用毫秒时间戳表示时间，这里统一在边界上换算一次，往内一律是带时区的
    `datetime`。非法输入抛 `ValueError` / `TypeError`，由调用方决定如何收敛。
    """

    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None:
        raise ValidationError(f"{field} 必须带时区")

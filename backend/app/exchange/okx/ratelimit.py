"""令牌桶限流。

上游按 IP 计窗口配额（例如 20 次 / 2 秒），令牌桶把「窗口配额」摊平成
「每秒补充多少令牌」，请求前取一个令牌即可保证不会连续打满窗口。

时钟与休眠可注入，测试里用假时钟就能确定性地断言等待时长，不真的 sleep。
"""

from __future__ import annotations

import time
from collections.abc import Callable

__all__ = ["TokenBucket"]


class TokenBucket:
    """固定容量、匀速补充的令牌桶。"""

    def __init__(
        self,
        capacity: int,
        refill_per_second: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if capacity < 1:
            raise ValueError("容量必须为正整数")
        if refill_per_second <= 0:
            raise ValueError("补充速率必须为正数")
        self._capacity = float(capacity)
        self._refill = float(refill_per_second)
        self._clock = clock
        self._sleep = sleep
        self._tokens = float(capacity)
        self._updated = clock()

    @property
    def capacity(self) -> float:
        """桶容量。"""

        return self._capacity

    def acquire(self, tokens: int = 1) -> None:
        """取走 `tokens` 个令牌；不够时休眠到够为止。"""

        if tokens < 1 or tokens > self._capacity:
            raise ValueError(f"单次取用令牌数必须在 1..{int(self._capacity)} 之间")
        self._replenish()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return
        wait = (tokens - self._tokens) / self._refill
        self._sleep(wait)
        # 睡满 `wait` 恰好补足 `tokens` 个令牌，取用后余额为 0；
        # 用「虚拟时间」推进，真实时钟是否同时前进都不影响记账。
        self._tokens = 0.0
        self._updated += wait

    def _replenish(self) -> None:
        now = self._clock()
        elapsed = now - self._updated
        if elapsed <= 0:
            return
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill)
        self._updated = now

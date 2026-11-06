"""限流与重试：OKX 的两种失败形态共用同一套退避。

实测（`docs/risk/external-dependencies.md` §2.4）：
- `/api/v5/market/candles` 约 40 次/2s，超限返回 **HTTP 429**；
- `/api/v5/market/history-candles` 约 20 次/2s，超限返回 **HTTP 200 + body code=50011**。

两者都必须重试，因此统一抽象为 `RateLimitedError`。重试耗尽抛
`UpstreamUnavailable`，由采集任务收敛为 `partial` 并写 `data_quality_issue`。
"""

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

# OKX 的限流错误码（50011 = Too Many Requests）。
OKX_RATE_LIMIT_CODES = frozenset({"50011", "50013"})


class UpstreamError(Exception):
    """上游返回了不可直接使用的错误。"""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class RateLimitedError(UpstreamError):
    """触发限流（HTTP 429 或 code=50011），重试可能成功。"""


class TransientUpstreamError(UpstreamError):
    """临时性失败（网络错误、5xx），重试可能成功。"""


class UpstreamUnavailable(UpstreamError):
    """重试耗尽：本次采集必须降级为 partial / MISSING_SOURCE。"""


class TokenBucket:
    """滑动窗口限流器：窗口期内最多 `capacity` 次请求。

    `clock`/`sleep` 可注入，单测里不需要真的等待。
    """

    def __init__(
        self,
        capacity: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        self._window = window_seconds
        self._clock = clock
        self._sleep = sleep
        self._calls: deque[float] = deque()

    async def acquire(self) -> None:
        """阻塞直到窗口内可再发一次请求。"""

        while True:
            now = self._clock()
            while self._calls and now - self._calls[0] >= self._window:
                self._calls.popleft()
            if len(self._calls) < self._capacity:
                self._calls.append(now)
                return
            wait = self._window - (now - self._calls[0])
            await self._sleep(max(wait, 0.0))


class RetryPolicy:
    """指数退避重试；429 与 code=50011 视为同一类可重试错误。"""

    def __init__(
        self,
        *,
        max_retries: int = 4,
        base_delay: float = 0.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._sleep = sleep
        self.attempts = 0

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        """执行操作直到成功或用尽重试次数。"""

        self.attempts = 0
        last_error: UpstreamError | None = None
        for attempt in range(self._max_retries + 1):
            self.attempts = attempt + 1
            try:
                return await operation()
            except (RateLimitedError, TransientUpstreamError) as exc:
                last_error = exc
                if attempt >= self._max_retries:
                    break
                await self._sleep(self._base_delay * (2**attempt))
        raise UpstreamUnavailable(
            f"upstream unavailable after {self.attempts} attempts: {last_error}",
            code=getattr(last_error, "code", None),
        )

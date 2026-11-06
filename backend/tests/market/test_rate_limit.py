"""限流与重试（AC4）：HTTP 429 与 HTTP 200+code=50011 走同一退避。"""

import httpx
import pytest

from app.adapters.okx.client import OkxClient
from app.adapters.okx.rate_limit import (
    RateLimitedError,
    RetryPolicy,
    TokenBucket,
    UpstreamUnavailable,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


async def test_token_bucket_waits_for_window_slot() -> None:
    clock = FakeClock()
    bucket = TokenBucket(2, 2.0, clock=clock, sleep=clock.sleep)
    await bucket.acquire()
    await bucket.acquire()
    await bucket.acquire()
    assert clock.slept == [2.0]
    assert clock.now == 2.0


async def test_retry_policy_backs_off_then_succeeds() -> None:
    clock = FakeClock()
    calls = {"count": 0}

    async def operation() -> str:
        calls["count"] += 1
        if calls["count"] < 3:
            raise RateLimitedError("too many requests")
        return "ok"

    policy = RetryPolicy(max_retries=4, base_delay=0.5, sleep=clock.sleep)
    assert await policy.run(operation) == "ok"
    assert policy.attempts == 3
    assert clock.slept == [0.5, 1.0]


async def test_retry_policy_exhaustion_raises_upstream_unavailable() -> None:
    clock = FakeClock()

    async def operation() -> str:
        raise RateLimitedError("too many requests")

    policy = RetryPolicy(max_retries=2, base_delay=0.5, sleep=clock.sleep)
    with pytest.raises(UpstreamUnavailable):
        await policy.run(operation)
    assert policy.attempts == 3


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(429, json={"code": "50011", "msg": "Too Many Requests", "data": []}),
        httpx.Response(200, json={"code": "50011", "msg": "Too Many Requests", "data": []}),
    ],
    ids=["http-429", "http-200-code-50011"],
)
async def test_client_retries_both_rate_limit_shapes(failure: httpx.Response) -> None:
    clock = FakeClock()
    seen = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["count"] += 1
        if seen["count"] < 3:
            return failure
        return httpx.Response(200, json={"code": "0", "msg": "", "data": [{"ok": True}]})

    client = OkxClient(
        "https://www.okx.com",
        transport=httpx.MockTransport(handler),
        max_retries=4,
        backoff_seconds=0.5,
        sleep=clock.sleep,
    )
    try:
        data = await client.get("/api/v5/market/candles", {"instId": "AAPL-USDT-SWAP"})
    finally:
        await client.aclose()
    assert data == [{"ok": True}]
    assert seen["count"] == 3
    assert client.attempts == 3
    assert clock.slept == [0.5, 1.0]

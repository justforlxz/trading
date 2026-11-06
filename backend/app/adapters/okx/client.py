"""OKX 公共 REST 客户端：限流 + 重试 + 统一错误映射。

只暴露只读公开端点；不引入 API key、不访问私有/下单接口（P1 边界）。
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.adapters.okx.rate_limit import (
    OKX_RATE_LIMIT_CODES,
    RateLimitedError,
    RetryPolicy,
    TokenBucket,
    TransientUpstreamError,
    UpstreamError,
)

logger = logging.getLogger(__name__)

USER_AGENT = "trading-backend/0.1 (+public market data)"


class OkxClient:
    """极薄的 httpx 封装：把上游错误码翻译成本层异常。"""

    def __init__(
        self,
        base_url: str = "https://www.okx.com",
        timeout_seconds: float = 10.0,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        candles_rate_limit: int = 40,
        history_rate_limit: int = 20,
        window_seconds: float = 2.0,
        max_retries: int = 4,
        backoff_seconds: float = 0.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        self._retry = RetryPolicy(max_retries=max_retries, base_delay=backoff_seconds, sleep=sleep)
        self._limiters: dict[str, TokenBucket] = {
            "instruments": TokenBucket(20, window_seconds, sleep=sleep),
            "candles": TokenBucket(candles_rate_limit, window_seconds, sleep=sleep),
            "history": TokenBucket(history_rate_limit, window_seconds, sleep=sleep),
            "ticker": TokenBucket(20, window_seconds, sleep=sleep),
        }

    @property
    def attempts(self) -> int:
        """最近一次请求实际尝试次数（测试与可观测性用）。"""

        return self._retry.attempts

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "OkxClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def get(
        self,
        path: str,
        params: dict[str, str] | None = None,
        *,
        limiter: str = "candles",
    ) -> list[dict[str, Any]]:
        """GET 并返回 `data` 数组；限流与重试在内部完成。"""

        bucket = self._limiters[limiter]

        async def attempt() -> list[dict[str, Any]]:
            await bucket.acquire()
            return await self._request(path, params)

        return await self._retry.run(attempt)

    async def _request(self, path: str, params: dict[str, str] | None) -> list[dict[str, Any]]:
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:  # 网络层错误按临时失败重试
            raise TransientUpstreamError(f"okx request failed: {exc}") from exc

        if response.status_code == 429:
            raise RateLimitedError(f"okx rate limited: {path}", code="429")
        if response.status_code >= 500:
            raise TransientUpstreamError(
                f"okx server error {response.status_code}: {path}", code=str(response.status_code)
            )
        if response.status_code >= 400:
            raise UpstreamError(
                f"okx http error {response.status_code}: {path}", code=str(response.status_code)
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError(f"okx returned non-json body: {path}") from exc

        code = str(payload.get("code", ""))
        if code in OKX_RATE_LIMIT_CODES:
            raise RateLimitedError(f"okx rate limited (code={code}): {path}", code=code)
        if code != "0":
            raise UpstreamError(
                f"okx error code={code} msg={payload.get('msg')}: {path}", code=code
            )
        data = payload.get("data") or []
        if not isinstance(data, list):
            raise UpstreamError(f"okx returned unexpected data shape: {path}")
        return data

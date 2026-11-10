"""OKX 公开 REST 客户端：限流、有限重试、错误收敛。

客户端只负责传输与封包校验，不解释业务字段；字段到中立数据结构的映射在
`market` 与 `instruments` 里完成。所有上游故障都在这里收敛成
`ExchangeError`，业务侧不会看到 httpx 的异常类型。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.exchange.errors import ExchangeError, RateLimitedError
from app.exchange.okx.errors import data_of
from app.exchange.okx.ratelimit import TokenBucket

__all__ = ["BACKOFF_BASE_SECONDS", "OkxClient"]

# 限流重试的初始退避秒数，之后按 2 的幂递增。
BACKOFF_BASE_SECONDS = 0.25


class OkxClient:
    """带令牌桶与限流重试的 REST 客户端。

    `transport` 用于注入自定义传输层（本地联调或测试），注入后不会发起
    真实网络请求；`sleep` 可注入以便测试确定性断言退避次数与时长。
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        bucket: TokenBucket | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._sleep = sleep
        self._max_retries = self._settings.okx_http_max_retries
        self._bucket = bucket or TokenBucket(
            self._settings.okx_rate_limit_capacity,
            self._settings.okx_rate_limit_refill_per_second,
            sleep=sleep,
        )
        self._client = httpx.Client(
            base_url=self._settings.okx_rest_base_url,
            timeout=self._settings.okx_http_timeout_seconds,
            transport=transport,
        )

    def get(self, path: str, params: dict[str, Any] | None = None) -> list[Any]:
        """GET 一个公开接口并返回应答体的 `data` 列表。

        命中限流（HTTP 429 或上游限流返回码）时按指数退避重试，超过配置的
        重试上限后抛 `RateLimitedError`；其余上游错误立即抛 `ExchangeError`。
        """

        attempt = 0
        while True:
            self._bucket.acquire()
            try:
                return self._fetch(path, params or {})
            except RateLimitedError:
                if attempt >= self._max_retries:
                    raise
                self._sleep(BACKOFF_BASE_SECONDS * 2**attempt)
                attempt += 1

    def close(self) -> None:
        """释放底层连接。"""

        self._client.close()

    def __enter__(self) -> OkxClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _fetch(self, path: str, params: dict[str, Any]) -> list[Any]:
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise ExchangeError(f"请求 {path} 失败:{exc}") from exc
        if response.status_code == 429:
            raise RateLimitedError(f"请求 {path} 返回 HTTP 429(Too Many Requests)")
        if response.status_code >= 400:
            raise ExchangeError(f"请求 {path} 返回 HTTP {response.status_code}")
        return data_of(self._payload(response, path), endpoint=path)

    @staticmethod
    def _payload(response: httpx.Response, path: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ExchangeError(f"请求 {path} 返回非 JSON 应答") from exc
        if not isinstance(payload, dict):
            raise ExchangeError(f"请求 {path} 返回结构异常")
        return payload

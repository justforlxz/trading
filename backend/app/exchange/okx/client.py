"""OKX REST 客户端：限流、有限重试、错误收敛。

客户端只负责传输与封包校验，不解释业务字段；字段到中立数据结构的映射在
`market`、`instruments` 与 `private` 里完成。所有上游故障都在这里收敛成
`ExchangeError`，业务侧不会看到 httpx 的异常类型。

签名不在这里算：签名串必须与真实发出的路径、请求体逐字节相同，因此由调用方
（`private`）拼好查询串与请求体、算好签名头之后传进来，本类只负责发出去。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.exchange.errors import ExchangeError, RateLimitedError
from app.exchange.okx.errors import RATE_LIMIT_CODES, data_of
from app.exchange.okx.ratelimit import TokenBucket

__all__ = ["BACKOFF_BASE_SECONDS", "OkxClient"]

# 限流重试的初始退避秒数，之后按 2 的幂递增。
BACKOFF_BASE_SECONDS = 0.25


def _error_of(response: httpx.Response) -> tuple[str | None, str | None]:
    """HTTP 4xx/5xx 应答体里的 `(code, msg)`；不是 JSON 就都没有。"""

    try:
        payload = response.json()
    except ValueError:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    code = payload.get("code")
    message = payload.get("msg")
    return (str(code) if code else None, str(message) if message else None)


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

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
        tolerate: frozenset[str] = frozenset(),
    ) -> list[Any]:
        """GET 一个接口并返回应答体的 `data` 列表。

        命中限流（HTTP 429 或上游限流返回码）时按指数退避重试，超过配置的
        重试上限后抛 `RateLimitedError`；其余上游错误立即抛 `ExchangeError`。

        私有接口自己算好查询串并连同签名头一起传入（签名串必须与真实发出的路径
        逐字节相同），此时不要再给 `params`。
        """

        return self._send("GET", path, params=params, headers=headers, tolerate=tolerate)

    def post(
        self,
        path: str,
        *,
        content: str,
        headers: dict[str, str] | None = None,
        tolerate: frozenset[str] = frozenset(),
    ) -> list[Any]:
        """POST 一个接口（请求体是已序列化好的字符串，签名按这段字节算）。"""

        return self._send("POST", path, content=content, headers=headers, tolerate=tolerate)

    def close(self) -> None:
        """释放底层连接。"""

        self._client.close()

    def __enter__(self) -> OkxClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        content: str | None = None,
        headers: dict[str, str] | None = None,
        tolerate: frozenset[str] = frozenset(),
    ) -> list[Any]:
        attempt = 0
        while True:
            self._bucket.acquire()
            try:
                return self._fetch(
                    method,
                    path,
                    params=params,
                    content=content,
                    headers=headers,
                    tolerate=tolerate,
                )
            except RateLimitedError:
                if attempt >= self._max_retries:
                    raise
                self._sleep(BACKOFF_BASE_SECONDS * 2**attempt)
                attempt += 1

    def _fetch(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None,
        content: str | None,
        headers: dict[str, str] | None,
        tolerate: frozenset[str],
    ) -> list[Any]:
        try:
            response = self._client.request(
                method,
                path,
                params=params,
                content=content,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise ExchangeError(f"请求 {path} 失败:{exc}") from exc
        if response.status_code >= 400:
            # 上游对参数类错误用 HTTP 4xx，但业务码仍写在应答体里（例如 51000）；
            # 丢掉它，排障就只剩一个状态码。
            code, message = _error_of(response)
            detail = f":{message}" if message else ""
            failure = f"请求 {path} 返回 HTTP {response.status_code}{detail}"
            # 限流判定只看返回码：HTTP 429 与应答体里的 50011/50013 是同一件事，
            # 前者以前不带上游码、后者以前不重试，同一个故障两种结局。
            if response.status_code == 429 or code in RATE_LIMIT_CODES:
                raise RateLimitedError(failure, code=code)
            raise ExchangeError(failure, code=code)
        return data_of(self._payload(response, path), endpoint=path, tolerate=tolerate)

    @staticmethod
    def _payload(response: httpx.Response, path: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ExchangeError(f"请求 {path} 返回非 JSON 应答") from exc
        if not isinstance(payload, dict):
            raise ExchangeError(f"请求 {path} 返回结构异常")
        return payload

"""HTTP 通道共用的有界重试：一次投递最多发几次、失败原因怎么写。

重试是**投递内部**的退避，不是周期任务：只有这次投递失败时才等待，次数与等待时间
都是常量，用尽即把失败原因返回给注册表。本目录里没有任何周期性动作的入口，也没有
常驻循环——这里只有一次请求加上有限次等待。

失败原因由本模块统一措辞，且**永不包含请求地址**：Telegram 的地址里带着 bot token，
把地址写进错误信息等于把令牌写进投递台账。

请求也**不走 `httpx.Client`**：它在 `INFO` 级别会打印一行
`HTTP Request: POST <完整地址> "HTTP/1.1 200 OK"`，而 Telegram 的令牌就在地址路径里，
进程以默认 `LOG_LEVEL=INFO` 运行时会把令牌原文写进日志。这里直接调用
`httpx.AsyncBaseTransport.handle_async_request`，那行日志不会产生。

超时改由 `asyncio.wait_for` 兜住，且**发请求与读响应体在同一个超时窗口里**：上游先回
响应头、再慢慢吐 body 的写法很常见，只包住「拿到响应头」等于没有上限。一次请求最多
`TIMEOUT_SECONDS` 秒，与 `httpx.Client(timeout=...)` 的口径一致。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import httpx

__all__ = [
    "MAX_RETRY_AFTER_SECONDS",
    "RETRY_DELAYS",
    "TIMEOUT_SECONDS",
    "post_json",
]

#: 每次重试前的等待（秒）：2s / 8s / 30s，共 3 次重试；加上首次请求最多 4 次请求。
RETRY_DELAYS: tuple[float, ...] = (2.0, 8.0, 30.0)
#: 单次请求超时（秒）。
TIMEOUT_SECONDS = 10.0
#: 429 的 `retry_after` 上限（秒）：上游给多少就等多少，但不能让它把投递拖成无界。
MAX_RETRY_AFTER_SECONDS = 60.0

Sleep = Callable[[float], Awaitable[None]]


async def post_json(
    url: str,
    *,
    content: bytes,
    headers: Mapping[str, str],
    transport: httpx.AsyncBaseTransport | None = None,
    sleep: Sleep = asyncio.sleep,
) -> str | None:
    """把 JSON 请求体发出去；成功返回 `None`，失败返回人可读原因。

    重试规则：

    - 网络错误、超时、5xx、408、429 → 有界退避重试；429 带 `retry_after` 时按它等待。
    - 其它 4xx（401、400 等）是永久错误，立即返回，不再重试。
    """

    total = len(RETRY_DELAYS) + 1
    failure = _Failure(reason="未知错误")
    # 测试注入的 transport 由调用方管理；没注入时自己建一条并在用完后关掉。
    channel = transport if transport is not None else httpx.AsyncHTTPTransport()
    try:
        for attempt in range(total):
            if attempt:
                pause = RETRY_DELAYS[attempt - 1] if failure.pause is None else failure.pause
                await sleep(pause)
            outcome = await _attempt(channel, url, content=content, headers=headers)
            if outcome is None:
                return None
            failure = outcome
            if not failure.retry:
                return failure.reason
    finally:
        if transport is None:
            await channel.aclose()
    return f"{failure.reason}，已尝试 {total} 次"


@dataclass(frozen=True, slots=True)
class _Failure:
    """一次失败的描述：`retry` 决定还试不试，`pause` 是上游要求的等待（缺失走固定退避）。"""

    reason: str
    retry: bool = True
    pause: float | None = None


async def _attempt(
    channel: httpx.AsyncBaseTransport,
    url: str,
    *,
    content: bytes,
    headers: Mapping[str, str],
) -> _Failure | None:
    """发一次请求：成功返回 `None`。不经过 `httpx.Client`，所以不会写访问日志。"""

    request = httpx.Request("POST", url, content=content, headers=headers)
    try:
        response = await asyncio.wait_for(_exchange(channel, request), timeout=TIMEOUT_SECONDS)
    except (TimeoutError, httpx.TimeoutException):
        return _Failure(f"请求超时（{TIMEOUT_SECONDS:g} 秒）")
    except httpx.HTTPError as exc:
        return _Failure(f"网络错误：{type(exc).__name__}")

    try:
        status = response.status_code
        if 200 <= status < 300:
            return None
        if not _retryable(status):
            return _Failure(f"HTTP {status}（永久错误，不重试）", retry=False)
        retry_after = _retry_after(response)
        if retry_after is None:
            return _Failure(f"HTTP {status}")
        return _Failure(
            f"HTTP {status}（上游要求等待 {retry_after:g} 秒）",
            pause=min(retry_after, MAX_RETRY_AFTER_SECONDS),
        )
    finally:
        await response.aclose()


async def _exchange(channel: httpx.AsyncBaseTransport, request: httpx.Request) -> httpx.Response:
    """发请求并读完响应体；两段都在调用方 `wait_for` 的同一个超时窗口里。"""

    response = await channel.handle_async_request(request)
    try:
        await response.aread()
    except BaseException:  # 含超时取消：先释放连接再交给上层
        await response.aclose()
        raise
    return response


def _retryable(status: int) -> bool:
    """可恢复的失败：上游临时故障、限流与请求超时。"""

    return status >= 500 or status in (408, 429)


def _retry_after(response: httpx.Response) -> float | None:
    """429 的等待秒数：先看 `Retry-After` 头，再看 Telegram 的 `parameters.retry_after`。"""

    header = response.headers.get("retry-after", "").strip()
    if header:
        try:
            return max(float(header), 0.0)
        except ValueError:
            pass
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    parameters = body.get("parameters")
    if not isinstance(parameters, dict):
        return None
    value = parameters.get("retry_after")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return max(float(value), 0.0)

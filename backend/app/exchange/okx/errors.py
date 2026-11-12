"""上游应答封包解析。

上游把失败也放在 HTTP 200 的应答体里（`code` / `msg`），这里把它翻译成
本层异常：限流类返回码单独成类，其余一律 `ExchangeError` 并保留返回码。
"""

from __future__ import annotations

from typing import Any

from app.exchange.errors import ExchangeError, RateLimitedError

__all__ = ["RATE_LIMIT_CODES", "data_of"]

# 限流相关返回码：上游既可能放在 HTTP 200 的应答体里，也可能配 HTTP 429。
RATE_LIMIT_CODES: frozenset[str] = frozenset({"50011", "50013"})


def data_of(
    payload: dict[str, Any],
    *,
    endpoint: str,
    tolerate: frozenset[str] = frozenset(),
) -> list[Any]:
    """取出成功应答的 `data`；`code` 非 0 时抛对应异常。

    `tolerate` 是「这个返回码仍然带着可用的逐条结果」的集合：下单与撤单接口在失败
    时返回 `code: "1"` 加 `data[0].sCode`，具体原因写在逐条结果里，整体抛异常就会
    把它丢掉。只有明确知道要自己解释 `sCode` 的调用方才会传这个集合。
    """

    code = str(payload.get("code", ""))
    if code == "0" or code in tolerate:
        data = payload.get("data")
        return list(data) if isinstance(data, list) else []
    message = str(payload.get("msg") or "上游返回失败")
    if code in RATE_LIMIT_CODES:
        raise RateLimitedError(f"{endpoint} 触达上游限流:{message}", code=code)
    raise ExchangeError(f"{endpoint} 返回错误:{message}", code=code)

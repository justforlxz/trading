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


def data_of(payload: dict[str, Any], *, endpoint: str) -> list[Any]:
    """取出成功应答的 `data`；`code` 非 0 时抛对应异常。"""

    code = str(payload.get("code", ""))
    if code == "0":
        data = payload.get("data")
        return list(data) if isinstance(data, list) else []
    message = str(payload.get("msg") or "上游返回失败")
    if code in RATE_LIMIT_CODES:
        raise RateLimitedError(f"{endpoint} 触达上游限流:{message}", code=code)
    raise ExchangeError(f"{endpoint} 返回错误:{message}", code=code)

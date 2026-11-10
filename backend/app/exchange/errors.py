"""交易所适配层的异常类型。

上游返回码、HTTP 状态与网络故障都在适配层内收敛成 `ExchangeError` 或它的子类，
业务侧不需要理解上游协议。

`ExchangeError` 继承 `core.UpstreamError`：交易所不可用属于「上游故障」，跨模块
统一按 `TradingError` 处理，API 边界不必为交易所单独写一条分支。
"""

from __future__ import annotations

from app.core import UpstreamError

__all__ = ["ExchangeError", "RateLimitedError"]


class ExchangeError(UpstreamError):
    """交易所交互失败。

    `code` 保留上游业务返回码（如 OKX 的 50011、51001），便于排障与日志检索；
    网络层、解析层错误没有上游返回码，保持为 None。
    """

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code

    def __str__(self) -> str:
        detail = super().__str__()
        if self.code is None:
            return detail
        return f"[{self.code}] {detail}"


class RateLimitedError(ExchangeError):
    """上游限流且重试次数已耗尽。

    语义上仍属 `ExchangeError`，调用方可以只捕获基类；需要区分限流
    （例如退避更久后再试）时捕获这个子类。
    """

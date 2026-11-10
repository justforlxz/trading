"""交易所适配层的异常类型。

业务模块只感知这里的异常：上游返回码、HTTP 状态与网络故障都在适配层内
收敛成 `ExchangeError` 或它的子类，业务侧不需要理解上游协议。
"""

from __future__ import annotations

__all__ = ["ExchangeError", "RateLimitedError"]


class ExchangeError(Exception):
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

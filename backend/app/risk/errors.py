"""风控域错误。

与 ``app.backtest.errors.BacktestError`` 同构，由 API 层转换成统一错误信封。
"""

from __future__ import annotations

from typing import Any


class RiskError(Exception):
    """带确定错误码的风控错误。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


__all__ = ["RiskError"]

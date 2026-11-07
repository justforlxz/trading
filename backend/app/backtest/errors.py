"""回测领域错误。

与 `strategy.core.constraints.ConstraintViolation` 同构但独立：`backtest` 不允许
依赖 `strategy`（分层红线），`code` 仍原样进入统一错误信封，供前端与测试断言。
"""

from __future__ import annotations

from typing import Any


class BacktestError(Exception):
    """`code` 进入 API 错误体，`status_code` 决定 HTTP 状态。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


__all__ = ["BacktestError"]

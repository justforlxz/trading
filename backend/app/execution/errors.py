"""执行层业务错误：携带稳定 code 供 API 组装错误信封。"""

from typing import Any


class ExecutionError(Exception):
    """执行域错误；`code` 与 api-contract §3.9 的取值一一对应。"""

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


__all__ = ["ExecutionError"]

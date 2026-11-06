"""统一错误信封 `{error: {code, message, details, request_id}}`（api-contract §1.4）。"""

from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

REQUEST_ID_HEADER = "X-Request-ID"


class ApiError(Exception):
    """业务错误：由路由显式抛出，携带稳定 code 供前端分支。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def request_id_of(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else uuid4().hex


def envelope(
    request: Request, *, code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id_of(request),
        }
    }


_SCALARS = (str, int, float, bool)


def _safe_validation_errors(error: RequestValidationError) -> list[dict[str, Any]]:
    """校验详情必须可 JSON 序列化：自定义校验器 `raise ValueError` 会带异常对象进 `ctx`。"""

    safe: list[dict[str, Any]] = []
    for item in error.errors():
        entry: dict[str, Any] = {}
        for key, value in item.items():
            if key == "ctx" and isinstance(value, dict):
                entry[key] = {
                    ctx_key: ctx_value
                    if ctx_value is None or isinstance(ctx_value, _SCALARS)
                    else str(ctx_value)
                    for ctx_key, ctx_value in value.items()
                }
            elif (
                key == "input"
                and value is not None
                and not isinstance(value, (*_SCALARS, list, dict))
            ):
                entry[key] = str(value)
            else:
                entry[key] = value
        safe.append(entry)
    return safe


def install_error_handlers(app: FastAPI) -> None:
    """把三类异常统一成同一信封（业务错误、参数校验、HTTP 状态）。"""

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content=envelope(
                request, code=error.code, message=error.message, details=error.details
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=envelope(
                request,
                code="VALIDATION_ERROR",
                message="request validation failed",
                details={"errors": _safe_validation_errors(error)},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, error: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content=envelope(
                request,
                code=f"HTTP_{error.status_code}",
                message=str(error.detail),
            ),
        )


__all__ = ["REQUEST_ID_HEADER", "ApiError", "envelope", "install_error_handlers", "request_id_of"]

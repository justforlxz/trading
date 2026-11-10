"""域异常 → HTTP 响应的唯一翻译点。

业务模块只抛 `app.core` 的异常并自带 `http_status`，这里只负责把它们转成与
FastAPI 默认错误同形的 `{"detail": ...}`，让前端不必区分错误来源。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core import TradingError

__all__ = ["register_error_handlers"]


def register_error_handlers(app: FastAPI) -> None:
    """注册统一的域异常处理；请求校验错误仍由 FastAPI 自己的 422 处理。"""

    @app.exception_handler(TradingError)
    async def _handle_trading_error(_request: Request, exc: TradingError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content={"detail": str(exc)})

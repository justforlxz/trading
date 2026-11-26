"""域异常 → HTTP 响应的唯一翻译点。

业务模块只抛 `app.core` 的异常并自带 `http_status`，这里只负责把它们转成与
FastAPI 默认错误同形的 `{"detail": ...}`，让前端不必区分错误来源。

## 对外文案与日志的分工

响应体只放**用户能据此行动**的话：领域错误（`ValidationError`、`NotFound` 等）
用自己的消息；上游故障（`UpstreamError` 及其子类）换成 `public_message` 里的固定
文案，因为它的消息里带着接口路径、查询串、errno 与 Python 异常原文——用户看不懂，
也没法据此做任何事。

原始信息不丢：上游故障在这里记一条 WARNING（含方法、路径与完整异常），排障看日志。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core import TradingError, UpstreamError

__all__ = ["register_error_handlers"]

logger = logging.getLogger(__name__)


def _public_detail(exc: TradingError) -> str:
    """响应体里的 `detail`：上游故障用固定文案，其余用自己的消息。"""

    return exc.public_message or str(exc)


def register_error_handlers(app: FastAPI) -> None:
    """注册统一的域异常处理；请求校验错误仍由 FastAPI 自己的 422 处理。"""

    @app.exception_handler(TradingError)
    async def _handle_trading_error(request: Request, exc: TradingError) -> JSONResponse:
        if isinstance(exc, UpstreamError):
            # 只记日志，不进响应体。`exc_info` 带上原始堆栈，errno 与上游返回码都在里面。
            logger.warning(
                "上游调用失败：%s %s -> %s",
                request.method,
                request.url.path,
                exc,
                exc_info=exc,
            )
        return JSONResponse(status_code=exc.http_status, content={"detail": _public_detail(exc)})

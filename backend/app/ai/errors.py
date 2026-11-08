"""助手域错误码: 统一进入 `{error:{code,message,details,request_id}}` 信封。"""

from __future__ import annotations

from typing import Any

from app.ports.ai_reads import AiReadsError

AI_NOT_CONFIGURED = "ai_not_configured"
AI_WRITE_FORBIDDEN = "ai_write_forbidden"
AI_INVALID_REQUEST = "ai_invalid_request"
AI_UPSTREAM_ERROR = "ai_upstream_error"
AI_TARGET_NOT_FOUND = "ai_target_not_found"
AI_STRATEGY_NOT_FOUND = "ai_strategy_not_found"
AI_BACKTEST_NOT_FOUND = "ai_backtest_not_found"
AI_OPPORTUNITY_NOT_FOUND = "ai_opportunity_not_found"
AI_INSTRUMENT_NOT_FOUND = "ai_instrument_not_found"

# 端口的 `not_found` 原因 -> (错误码, 默认文案); 全部 404。
_NOT_FOUND: dict[str, tuple[str, str]] = {
    "target_not_found": (AI_TARGET_NOT_FOUND, "目标股票不存在"),
    "strategy_not_found": (AI_STRATEGY_NOT_FOUND, "策略不存在"),
    "backtest_not_found": (AI_BACKTEST_NOT_FOUND, "回测不存在"),
    "opportunity_not_found": (AI_OPPORTUNITY_NOT_FOUND, "机会不存在"),
    "instrument_not_found": (AI_INSTRUMENT_NOT_FOUND, "标的不存在"),
}


class AiError(Exception):
    """`code` 进入 API 错误体, `status_code` 决定 HTTP 状态。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


def not_configured() -> AiError:
    return AiError(
        AI_NOT_CONFIGURED,
        "AI 助手未配置: 请显式设置 AI_ENABLED=true 并配齐 "
        "AI_PROVIDER/AI_MODEL/AI_BASE_URL/AI_API_KEY",
        status_code=503,
    )


def from_reads_error(exc: AiReadsError) -> AiError:
    """端口 `not_found` -> 404 `ai_*_not_found`; `no_data` 由调用方按 200 处理。"""

    code, message = _NOT_FOUND.get(exc.reason, (AI_INVALID_REQUEST, "读取失败"))
    return AiError(
        code,
        exc.message or message,
        status_code=404,
        details={"reason": exc.reason},
    )


__all__ = [
    "AI_BACKTEST_NOT_FOUND",
    "AI_INSTRUMENT_NOT_FOUND",
    "AI_INVALID_REQUEST",
    "AI_NOT_CONFIGURED",
    "AI_OPPORTUNITY_NOT_FOUND",
    "AI_STRATEGY_NOT_FOUND",
    "AI_TARGET_NOT_FOUND",
    "AI_UPSTREAM_ERROR",
    "AI_WRITE_FORBIDDEN",
    "AiError",
    "from_reads_error",
    "not_configured",
]

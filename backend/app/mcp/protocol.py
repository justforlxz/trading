"""JSON-RPC 2.0 报文构造（纯函数，无 IO）。

只做「请求对象 -> 响应对象」的成形与常量定义，方法分发在 `server.py`。
错误码沿用 JSON-RPC 2.0 规范：解析失败 -32700、非法请求 -32600、
方法不存在 -32601、参数错误 -32602、服务端错误 -32603。
"""

from __future__ import annotations

import json
from typing import Any

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
# -32000..-32099 留给实现自定义；scope 不足用它，便于客户端区分「业务失败」。
FORBIDDEN = -32003

PROTOCOL_VERSION = "2024-11-05"
REQUEST_ID_MAX = 256


def error_response(
    request_id: Any, code: int, message: str, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def result_response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def tool_result(payload: Any) -> dict[str, Any]:
    """MCP `CallToolResult`：载荷统一序列化成一段 JSON 文本。"""

    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}],
        "isError": False,
    }


def tool_error(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """工具失败用 `isError=true` + 结构化内容，客户端可稳定分支。"""

    body = {"error": {"code": code, "message": message, "details": details or {}}}
    return {
        "content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False, default=str)}],
        "isError": True,
    }


def is_valid_id(value: Any) -> bool:
    """`id` 允许字符串/数字/null；超长字符串一律当非法请求处理。"""

    if value is None or isinstance(value, bool):
        return value is None
    if isinstance(value, int | float):
        return True
    return isinstance(value, str) and len(value) <= REQUEST_ID_MAX


def wants_event_stream(accept: str | None) -> bool:
    return bool(accept) and "text/event-stream" in accept.lower()


def sse_body(payload: Any) -> str:
    return f"event: message\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


__all__ = [
    "FORBIDDEN",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "PROTOCOL_VERSION",
    "error_response",
    "is_valid_id",
    "result_response",
    "sse_body",
    "tool_error",
    "tool_result",
    "wants_event_stream",
]

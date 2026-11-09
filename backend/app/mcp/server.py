"""`/mcp`：Streamable HTTP 的 JSON-RPC 2.0 端点（支持 SSE 流式响应）。

入口顺序是固定的：先鉴权（失败 401 JSON，不是 JSON-RPC 错误），再解析报文，
再按方法分发；`tools/call` 每次调用都写一条审计，scope 不足返回 403。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.api.errors import ApiError
from app.api.v1.deps import session_dep
from app.backtest.errors import BacktestError
from app.mcp import audit, protocol
from app.mcp.auth import (
    McpAuthError,
    bearer_token,
    client_scopes,
    find_client,
    require_scope,
)
from app.mcp.models import SCOPE_READ, McpClient
from app.mcp.resources import read_resource, resource_list
from app.mcp.tools import TOOL_INDEX, ToolContext, ToolError, tool_definitions
from app.risk.errors import RiskError
from app.strategy.core.constraints import ConstraintViolation

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mcp"])

SessionDep = Annotated[AsyncSession, Depends(session_dep)]


async def current_client(request: Request, session: SessionDep) -> McpClient:
    """路由层鉴权：缺失/错误/已吊销的 token 一律 401。"""

    try:
        token = bearer_token(request.headers.get("authorization"))
        return await find_client(session, token)
    except McpAuthError as error:
        raise ApiError(error.code, error.message, status_code=error.status_code) from error


ClientDep = Annotated[McpClient, Depends(current_client)]


def _respond(request: Request, payload: Any, *, status_code: int) -> Response:
    if protocol.wants_event_stream(request.headers.get("accept")):
        return StreamingResponse(
            iter([protocol.sse_body(payload)]),
            status_code=status_code,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )
    return JSONResponse(payload, status_code=status_code)


def _latency_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _reason_of(arguments: dict[str, Any]) -> str | None:
    value = arguments.get("reason")
    return value if isinstance(value, str) and value.strip() else None


async def _call_tool(
    session: AsyncSession,
    client: McpClient,
    request_id: Any,
    params: Any,
) -> tuple[dict[str, Any], int]:
    started = time.perf_counter()
    if not isinstance(params, dict):
        return protocol.error_response(
            request_id, protocol.INVALID_PARAMS, "params must be an object"
        ), 200
    name = params.get("name")
    if not isinstance(name, str) or not name:
        return protocol.error_response(
            request_id, protocol.INVALID_PARAMS, "params.name is required"
        ), 200
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return protocol.error_response(
            request_id, protocol.INVALID_PARAMS, "params.arguments must be an object"
        ), 200

    tool = TOOL_INDEX.get(name)
    if tool is None:
        return protocol.error_response(
            request_id, protocol.INVALID_PARAMS, f"unknown tool: {name}"
        ), 200
    reason = _reason_of(arguments)

    # Scope：operate 工具要求 operate；read 工具 read/operate 均可。
    try:
        require_scope(client, tool.scope)
    except McpAuthError as error:
        await audit.record_call(
            session,
            client=client,
            tool=tool.name,
            arguments=arguments,
            status=audit.STATUS_DENIED,
            error_code=error.code,
            reason=reason,
            latency_ms=_latency_ms(started),
        )
        return protocol.error_response(
            request_id,
            protocol.FORBIDDEN,
            error.message,
            {"code": error.code, "scope": tool.scope, "scopes": sorted(client_scopes(client))},
        ), error.status_code

    # 操作类调用必须说明原因，否则审计无法回答「谁让它下的单」。
    if tool.scope != SCOPE_READ and reason is None:
        error = ToolError("reason_required", "操作类调用必须提供非空 reason")
        await audit.record_call(
            session,
            client=client,
            tool=tool.name,
            arguments=arguments,
            status=audit.STATUS_ERROR,
            error_code=error.code,
            latency_ms=_latency_ms(started),
        )
        return protocol.result_response(
            request_id, protocol.tool_error(error.code, error.message)
        ), 200

    ctx = ToolContext(session=session, client=client)
    try:
        payload = await tool.handler(ctx, arguments)
    except ToolError as error:
        await audit.record_call(
            session,
            client=client,
            tool=tool.name,
            arguments=arguments,
            status=audit.STATUS_ERROR,
            error_code=error.code,
            reason=reason,
            latency_ms=_latency_ms(started),
        )
        return protocol.result_response(
            request_id, protocol.tool_error(error.code, error.message, error.details)
        ), 200
    except (ConstraintViolation, BacktestError, RiskError) as error:
        await audit.record_call(
            session,
            client=client,
            tool=tool.name,
            arguments=arguments,
            status=audit.STATUS_ERROR,
            error_code=error.code,
            reason=reason,
            latency_ms=_latency_ms(started),
        )
        return protocol.result_response(
            request_id, protocol.tool_error(error.code, error.message, error.details)
        ), 200
    except ValidationError as error:
        await audit.record_call(
            session,
            client=client,
            tool=tool.name,
            arguments=arguments,
            status=audit.STATUS_ERROR,
            error_code="invalid_arguments",
            reason=reason,
            latency_ms=_latency_ms(started),
        )
        return protocol.result_response(
            request_id,
            protocol.tool_error("invalid_arguments", "参数校验未通过", {"errors": error.errors()}),
        ), 200
    except Exception:  # pragma: no cover - 兜底：内部错误也要留审计
        logger.exception("mcp tool failed: %s", tool.name)
        await audit.record_call(
            session,
            client=client,
            tool=tool.name,
            arguments=arguments,
            status=audit.STATUS_ERROR,
            error_code="internal_error",
            reason=reason,
            latency_ms=_latency_ms(started),
        )
        return protocol.error_response(request_id, protocol.INTERNAL_ERROR, "internal error"), 200

    await audit.record_call(
        session,
        client=client,
        tool=tool.name,
        arguments=arguments,
        status=audit.STATUS_OK,
        reason=reason,
        latency_ms=_latency_ms(started),
    )
    return protocol.result_response(request_id, protocol.tool_result(payload)), 200


async def _read_resource(
    session: AsyncSession, client: McpClient, request_id: Any, params: Any
) -> tuple[dict[str, Any], int]:
    started = time.perf_counter()
    if not isinstance(params, dict):
        return protocol.error_response(
            request_id, protocol.INVALID_PARAMS, "params must be an object"
        ), 200
    uri = params.get("uri")
    if not isinstance(uri, str) or not uri:
        return protocol.error_response(
            request_id, protocol.INVALID_PARAMS, "params.uri is required"
        ), 200
    try:
        require_scope(client, SCOPE_READ)
    except McpAuthError as error:
        await audit.record_call(
            session,
            client=client,
            tool="resources/read",
            arguments={"uri": uri},
            status=audit.STATUS_DENIED,
            error_code=error.code,
            latency_ms=_latency_ms(started),
        )
        return protocol.error_response(
            request_id, protocol.FORBIDDEN, error.message, {"code": error.code}
        ), error.status_code

    try:
        content = await read_resource(session, uri)
    except (ValueError, ConstraintViolation, BacktestError) as error:
        code = getattr(error, "code", "invalid_resource")
        await audit.record_call(
            session,
            client=client,
            tool="resources/read",
            arguments={"uri": uri},
            status=audit.STATUS_ERROR,
            error_code=code,
            latency_ms=_latency_ms(started),
        )
        return protocol.error_response(request_id, protocol.INVALID_PARAMS, str(error)), 200

    await audit.record_call(
        session,
        client=client,
        tool="resources/read",
        arguments={"uri": uri},
        status=audit.STATUS_OK,
        latency_ms=_latency_ms(started),
    )
    return protocol.result_response(request_id, {"contents": [content]}), 200


def _initialize_result() -> dict[str, Any]:
    return {
        "protocolVersion": protocol.PROTOCOL_VERSION,
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"subscribe": False, "listChanged": False},
        },
        "serverInfo": {"name": "trading-mcp", "version": __version__},
    }


async def _dispatch(
    session: AsyncSession, client: McpClient, message: Any
) -> tuple[dict[str, Any] | None, int]:
    started = time.perf_counter()
    if not isinstance(message, dict):
        return protocol.error_response(
            None, protocol.INVALID_REQUEST, "request must be an object"
        ), 200
    request_id = message.get("id")
    method = message.get("method")
    notification = "id" not in message

    if not isinstance(method, str) or not method:
        if notification:
            return None, 200
        return protocol.error_response(
            request_id, protocol.INVALID_REQUEST, "method is required"
        ), 200
    if not protocol.is_valid_id(request_id):
        return protocol.error_response(None, protocol.INVALID_REQUEST, "invalid request id"), 200

    if notification:
        # 生命周期通知（initialized 等）：不回包、不执行业务，只留一条审计。
        await audit.record_call(
            session,
            client=client,
            tool=method,
            arguments=message.get("params"),
            status=audit.STATUS_OK,
            latency_ms=_latency_ms(started),
        )
        return None, 200

    params = message.get("params")

    if method == "tools/call":
        return await _call_tool(session, client, request_id, params)
    if method == "resources/read":
        return await _read_resource(session, client, request_id, params)

    if method == "initialize":
        result: Any = _initialize_result()
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tool_definitions()}
    elif method == "resources/list":
        result = {"resources": resource_list()}
    else:
        return protocol.error_response(
            request_id, protocol.METHOD_NOT_FOUND, f"unknown method: {method}"
        ), 200

    await audit.record_call(
        session,
        client=client,
        tool=method,
        arguments=params,
        status=audit.STATUS_OK,
        latency_ms=_latency_ms(started),
    )
    return protocol.result_response(request_id, result), 200


@router.post("/mcp")
async def mcp_endpoint(
    request: Request,
    session: SessionDep,
    client: ClientDep,
) -> Response:
    """唯一的 MCP 入口：单请求与 batch 都支持，notification 回 202 空体。"""

    raw = await request.body()
    if not raw:
        return _respond(
            request,
            protocol.error_response(None, protocol.PARSE_ERROR, "empty request body"),
            status_code=400,
        )
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        return _respond(
            request,
            protocol.error_response(None, protocol.PARSE_ERROR, "invalid JSON"),
            status_code=400,
        )

    if isinstance(message, list):
        if not message:
            return _respond(
                request,
                protocol.error_response(None, protocol.INVALID_REQUEST, "empty batch"),
                status_code=400,
            )
        responses: list[Any] = []
        batch_status = 200
        for item in message:
            response, item_status = await _dispatch(session, client, item)
            if response is not None:
                responses.append(response)
            if item_status != 200:
                batch_status = item_status
        if not responses:
            return Response(status_code=202)
        # scope 不足在单请求上用 403 表达；batch 里各条目自带错误码，整体仍是 200。
        return _respond(request, responses, status_code=200 if len(responses) > 1 else batch_status)

    response, status_code = await _dispatch(session, client, message)
    if response is None:
        return Response(status_code=202)
    return _respond(request, response, status_code=status_code)


__all__ = ["current_client", "mcp_endpoint", "router"]

"""`trading-mcp`:stdio 包装器.

只做一件事:把 stdin 上每行 JSON-RPC 原样转发到 HTTP `/mcp`,再把响应写回
stdout.业务一律在服务端算,这里不缓存,不算数,不改写结果.

连接参数:`TRADING_MCP_URL`(默认 `http://127.0.0.1:8000/mcp`)与
`TRADING_MCP_TOKEN`(Bearer token).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

import httpx

DEFAULT_URL = "http://127.0.0.1:8000/mcp"
DEFAULT_TIMEOUT = 60.0


def target_config(environ: dict[str, str] | None = None) -> tuple[str, str]:
    values = os.environ if environ is None else environ
    url = values.get("TRADING_MCP_URL") or DEFAULT_URL
    token = values.get("TRADING_MCP_TOKEN") or ""
    return url, token


def _headers(token: str) -> dict[str, str]:
    headers = {"content-type": "application/json", "accept": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    return headers


async def forward(
    message: Any,
    *,
    url: str,
    token: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Any | None:
    """转发一条报文;服务端 202(notification)时返回 None."""

    async with httpx.AsyncClient(transport=transport, timeout=DEFAULT_TIMEOUT) as client:
        response = await client.post(url, json=message, headers=_headers(token))
    if response.status_code == 202 or not response.content:
        return None
    payload: Any = response.json()
    return payload


def _write(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


async def serve(url: str, token: str) -> None:
    """逐行转发 stdin;EOF 即退出."""

    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            return
        text = line.strip()
        if not text:
            continue
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            _write(_error(None, -32700, "invalid JSON on stdin"))
            continue
        request_id = message.get("id") if isinstance(message, dict) else None
        try:
            reply = await forward(message, url=url, token=token)
        except Exception as error:
            _write(_error(request_id, -32603, f"upstream error: {error}"))
            continue
        if reply is not None:
            _write(reply)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trading-mcp",
        description="stdio 包装器:把 JSON-RPC 转发到 trading 的 HTTP MCP 端点",
    )
    parser.add_argument("--url", default=None, help="覆盖 TRADING_MCP_URL")
    parser.add_argument("--token", default=None, help="覆盖 TRADING_MCP_TOKEN")
    args = parser.parse_args(argv)

    env_url, env_token = target_config()
    url = args.url or env_url
    token = (args.token or env_token).strip()
    if not token:
        sys.stderr.write("trading-mcp: TRADING_MCP_TOKEN is required\n")
        return 2
    try:
        asyncio.run(serve(url, token))
    except KeyboardInterrupt:  # pragma: no cover - 交互式中断
        return 130
    return 0


__all__ = ["DEFAULT_URL", "forward", "main", "serve", "target_config"]

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

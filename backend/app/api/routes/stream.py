"""浏览器推送入口 `/api/stream`：只做 WebSocket 收发与队列，订阅规则在 `app.stream`。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.stream import StreamHub

__all__ = ["stream_router"]

stream_router = APIRouter(tags=["stream"])


@stream_router.websocket("/stream")
async def stream_endpoint(websocket: WebSocket) -> None:
    """接受浏览器连接：一条接收订阅的读循环 + 一条写发送队列。

    Starlette 的 `send_json` 不能从多个任务并发调用；所有事件先进入本连接的队列，
    由唯一的写任务按顺序发出，避免行情与账户事件交错破坏帧。
    """

    await websocket.accept()
    hub: StreamHub = websocket.app.state.stream_hub
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    client = hub.register(queue.put_nowait)

    async def _sender() -> None:
        while True:
            event = await queue.get()
            if event is None:
                return
            await websocket.send_json(event)

    sender = asyncio.create_task(_sender(), name="trading-stream-sender")
    try:
        while True:
            message = await websocket.receive_json()
            await hub.handle(client, message)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(client)
        queue.put_nowait(None)
        try:
            await sender
        except Exception:
            sender.cancel()

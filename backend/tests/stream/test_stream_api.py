"""`/api/stream` WebSocket 端点：订阅消息进入 hub，事件按队列顺序发回浏览器。"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


class StubHub:
    """记录订阅消息并回一条事件，用来验证端点收发与队列，不启动 OKX 连接。"""

    def __init__(self) -> None:
        self.messages: list[Any] = []
        self.unregistered = False
        self._send: Any = None

    def register(self, send: Any) -> str:
        self._send = send
        return "client-1"

    def unregister(self, _client: str) -> None:
        self.unregistered = True

    async def handle(self, _client: str, message: Any) -> None:
        self.messages.append(message)
        self._send(
            {
                "type": "market.quote.updated",
                "as_of": "2026-11-13T09:00:00Z",
                "received_at": "2026-11-13T09:00:00.120Z",
                "data": {"inst_id": "XAAPL-USDT", "last": "231.42"},
            }
        )


def test_subscription_messages_reach_the_hub_and_events_reach_the_browser(
    client: TestClient,
) -> None:
    hub = StubHub()
    client.app.state.stream_hub = hub

    with client.websocket_connect("/api/stream") as websocket:
        websocket.send_json(
            {
                "action": "subscribe",
                "topics": [{"type": "quote", "inst_ids": ["XAAPL-USDT"]}],
            }
        )
        event = websocket.receive_json()

    assert hub.messages == [
        {"action": "subscribe", "topics": [{"type": "quote", "inst_ids": ["XAAPL-USDT"]}]}
    ]
    assert event["type"] == "market.quote.updated"
    assert event["data"]["last"] == "231.42"
    assert hub.unregistered is True

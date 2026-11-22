"""Webhook 端到端：本地起一个真实 HTTP 接收端，用同一 secret 对收到的原始字节验签。

与 `test_http_sinks.py` 的区别是**不拦请求**：这里真的走一次 TCP 与本机 echo 服务，
验证的是「服务端发出去的字节」与「接收方重算的签名」一致。接收端只监听回环地址，
不访问外网。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

from app.events import DomainEvent
from app.events.sinks.config import ChannelConfig
from app.events.sinks.webhook import SIGNATURE_HEADER, WebhookSink

SECRET = "echo-server-signing-secret"
MOMENT = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)

ALERT: dict[str, Any] = {
    "id": "al_XAAPL-USDT_20261120120000000000",
    "type": "price",
    "severity": "warning",
    "title": "价格偏离参考价",
    "detail": "XAAPL-USDT 最新成交价 101.5 高于 指数价 100，偏离 1.5%",
    "instrument_id": "XAAPL-USDT",
}


class _EchoServer(ThreadingHTTPServer):
    """只有一条记录的接收端：收到的那一份请求原样留着给用例验签。"""

    received: dict[str, Any]


class _EchoHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        cast(_EchoServer, self.server).received = {
            "body": self.rfile.read(length),
            "signature": self.headers.get(SIGNATURE_HEADER),
            "content_type": self.headers.get("content-type"),
        }
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_args: Any) -> None:
        """保持测试输出干净：不打印每个请求。"""


@contextmanager
def _echo_server() -> Iterator[_EchoServer]:
    server = _EchoServer(("127.0.0.1", 0), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)


def _event() -> DomainEvent:
    return DomainEvent(
        kind="alert",
        inst_id="XAAPL-USDT",
        payload={"rule_id": "price_deviation", "alert": dict(ALERT)},
        occurred_at=MOMENT,
    )


def test_webhook_is_signed_over_the_bytes_an_echo_server_receives() -> None:
    """AC3：本机 echo 服务用同一 secret 验签通过，八个字段齐全。"""

    with _echo_server() as server:
        port = server.server_address[1]
        config = ChannelConfig(
            webhook_url=f"http://127.0.0.1:{port}/hook",
            webhook_signing_secret=SECRET,
        )

        result = asyncio.run(WebhookSink(lambda: config).deliver(_event()))

        received = server.received
        expected = hmac.new(SECRET.encode(), received["body"], hashlib.sha256).hexdigest()

    assert result.status == "delivered"
    assert received["signature"] == f"sha256={expected}"
    assert received["content_type"] == "application/json"
    assert json.loads(received["body"]) == {
        "source": "trading",
        "id": ALERT["id"],
        "type": ALERT["type"],
        "severity": ALERT["severity"],
        "title": ALERT["title"],
        "detail": ALERT["detail"],
        "instrument_id": ALERT["instrument_id"],
        "occurred_at": "2026-11-20T12:00:00Z",
    }

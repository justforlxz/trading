"""Webhook 通道：把告警按固定 JSON 形状推给用户自己的接收地址。

请求体是**已序列化的字节**：签名必须对真正发出去的那串字节做 HMAC-SHA256，所以先
`dumps` 一次再签名，不再让 HTTP 客户端重新序列化一遍。

正文里除了六个结构化字段，还带一段 `message`：它由 `render.render_message` 渲染，
与浏览器通知、Telegram 消息逐字相同。结构化字段仍取自这一轮的第一条告警，接收方
要按条处理时用 `message` 判断合并后的条数。

配了 `WEBHOOK_SIGNING_SECRET` 才加签；不配就是不签名的纯 JSON 推送。签名头格式
`X-Trading-Signature: sha256=<hex>`，接收方用同一密钥对原始 body 重算即可校验。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import Callable

import httpx

from app.events.sinks.base import DeliveryResult, utc_moment
from app.events.sinks.config import ChannelConfig
from app.events.sinks.digest import DeliveryDigest
from app.events.sinks.http import Sleep, post_json
from app.events.sinks.render import render_message

__all__ = ["SIGNATURE_HEADER", "SOURCE", "WebhookSink"]

#: 推送来源标识：接收方据此区分同一个地址上的其它来源。
SOURCE = "trading"
SIGNATURE_HEADER = "X-Trading-Signature"
#: 接收方按这六个字段取正文；`source`、`message` 与 `occurred_at` 是信封。
FIELDS = ("id", "type", "severity", "title", "detail", "instrument_id")


class WebhookSink:
    """`POST {url}`；地址在每次投递时现读，设置页改完立即生效。"""

    name = "webhook"

    def __init__(
        self,
        config: Callable[[], ChannelConfig],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._config = config
        self._transport = transport
        self._sleep = sleep

    async def deliver(self, digest: DeliveryDigest) -> DeliveryResult:
        # 配置来自设置表的同步查询：挪到线程里，别占住事件循环。
        config = await asyncio.to_thread(self._config)
        if not config.webhook_url:
            return DeliveryResult(
                self.name,
                "failed",
                "未配置：请先在设置页填写 Webhook 接收地址",
            )
        body = render_body(digest)
        headers = {"Content-Type": "application/json"}
        if config.webhook_signing_secret:
            headers[SIGNATURE_HEADER] = sign(body, config.webhook_signing_secret)
        error = await post_json(
            config.webhook_url,
            content=body,
            headers=headers,
            transport=self._transport,
            sleep=self._sleep,
        )
        if error is not None:
            return DeliveryResult(self.name, "failed", error)
        return DeliveryResult(self.name, "delivered")


def render_body(digest: DeliveryDigest) -> bytes:
    """固定字段的 JSON 字节：键排序、无多余空白，签名与接收方校验用同一串字节。"""

    document: dict[str, object] = {"source": SOURCE}
    document.update({key: _text(digest.alert.get(key)) for key in FIELDS})
    document["message"] = render_message(digest)
    document["occurred_at"] = utc_moment(digest.occurred_at)
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sign(body: bytes, secret: str) -> str:
    """`sha256=<hex>`：对原始 body 字节做 HMAC-SHA256。"""

    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""

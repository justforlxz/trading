"""OKX 私有适配器：签名、长度换算、字段归一化与 MockTransport 请求。

`MockTransport` 意味着本文件里没有任何真实网络：请求只发给测试内的回调，
回调同时充当「交易所响应」。
"""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.adapters.okx.private import (
    OkxPrivateClient,
    build_prehash,
    build_request_path,
    build_timestamp,
    normalize_order,
    normalize_position,
    sign_request,
    to_exchange_size,
)
from app.adapters.okx.rate_limit import UpstreamError
from app.ports.private import OrderRequest

SECRET = "test-secret"
API_KEY = "test-key"
PASSPHRASE = "test-pass"
TIMESTAMP = "2020-12-08T09:08:57.715Z"
BALANCE_PATH = "/api/v5/account/balance?ccy=BTC"


def _stdlib_sign(secret: str, prehash: str) -> str:
    digest = hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def test_timestamp_has_millisecond_precision() -> None:
    moment = datetime(2020, 12, 8, 9, 8, 57, 715000, tzinfo=UTC)
    assert build_timestamp(moment) == TIMESTAMP
    assert build_timestamp(moment.replace(tzinfo=None).replace(tzinfo=UTC)) == TIMESTAMP


def test_prehash_is_documented_recipe() -> None:
    prehash = build_prehash(timestamp=TIMESTAMP, method="get", request_path=BALANCE_PATH)
    assert prehash == f"{TIMESTAMP}GET{BALANCE_PATH}"


def test_signature_matches_stdlib_and_fixed_vector() -> None:
    """固定向量覆盖「时间戳 + METHOD + requestPath + body」拼接顺序。

    OKX 文档页是脚本渲染的，本环境离线无法逐字抓取官方示例；因此这里用固定的
    `(secret, timestamp, path, body)` 组合做回归断言，等价于对签名原文逐字节校验。
    """

    expected = _stdlib_sign(SECRET, f"{TIMESTAMP}GET{BALANCE_PATH}")
    assert (
        sign_request(SECRET, timestamp=TIMESTAMP, method="GET", request_path=BALANCE_PATH)
        == expected
    )
    assert expected == "5KlCItRxE039QKll2OJlbYeUcSiPGR/z10UR7bbl68o="

    body = '{"instId":"BTC-USDT-SWAP"}'
    post_expected = _stdlib_sign(SECRET, f"{TIMESTAMP}POST/api/v5/trade/order{body}")
    assert post_expected == "pTcfOssGhm9sSvJrX7EenxdYrhHiqBkSG5mJc6vZoQg="
    assert (
        sign_request(
            SECRET,
            timestamp=TIMESTAMP,
            method="POST",
            request_path="/api/v5/trade/order",
            body=body,
        )
        == post_expected
    )


def test_request_path_drops_empty_params() -> None:
    assert build_request_path("/api/v5/trade/order", {"instId": "BTC", "ordId": None}) == (
        "/api/v5/trade/order?instId=BTC"
    )
    assert build_request_path("/api/v5/trade/order", {}) == "/api/v5/trade/order"


def test_to_exchange_size_converts_and_floors() -> None:
    assert to_exchange_size(Decimal("1"), ct_val=Decimal("0.01"), lot_sz=Decimal("1")) == Decimal(
        "100"
    )
    assert to_exchange_size(
        Decimal("0.019"), ct_val=Decimal("0.01"), lot_sz=Decimal("1")
    ) == Decimal("1")
    with pytest.raises(UpstreamError):
        to_exchange_size(Decimal("0.001"), ct_val=Decimal("0.01"), lot_sz=Decimal("1"))


def test_normalize_position_splits_net_mode() -> None:
    short = normalize_position(
        {"instId": "BTC-USDT-SWAP", "pos": "-2", "posSide": "net", "avgPx": "100", "upl": "-5"}
    )
    assert short is not None
    assert (short.position_side, short.quantity) == ("short", Decimal("2"))
    assert normalize_position({"instId": "BTC-USDT-SWAP", "pos": "0"}) is None


def test_normalize_order_keeps_raw_state_for_caller_mapping() -> None:
    order = normalize_order(
        {
            "clOrdId": "c1",
            "ordId": "1",
            "instId": "BTC-USDT-SWAP",
            "side": "buy",
            "posSide": "long",
            "state": "partially_filled",
            "sz": "10",
            "accFillSz": "4",
            "avgPx": "100",
            "fee": "-0.1",
            "uTime": "1700000000000",
        }
    )
    assert order.state == "partially_filled"
    assert order.filled_quantity == Decimal("4")
    assert order.updated_at == datetime.fromtimestamp(1700000000, tz=UTC)


def _client(handler) -> OkxPrivateClient:
    return OkxPrivateClient(
        "https://www.okx.com",
        api_key=API_KEY,
        api_secret=SECRET,
        passphrase=PASSPHRASE,
        contract_sizes={"BTC-USDT-SWAP": Decimal("0.01")},
        lot_sizes={"BTC-USDT-SWAP": Decimal("1")},
        transport=httpx.MockTransport(handler),
    )


async def test_place_order_signs_request_and_converts_size() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "code": "0",
                "msg": "",
                "data": [{"ordId": "42", "clOrdId": "c1", "sCode": "0", "sMsg": ""}],
            },
        )

    client = _client(handler)
    try:
        ack = await client.place_order(
            OrderRequest(
                inst_id="BTC-USDT-SWAP",
                side="buy",
                position_side="long",
                order_type="market",
                quantity=Decimal("1"),
                price=None,
                client_order_id="c1",
            )
        )
    finally:
        await client.aclose()

    assert ack.exchange_order_id == "42"
    assert ack.client_order_id == "c1"
    assert len(calls) == 1

    request = calls[0]
    assert request.url.path == "/api/v5/trade/order"
    assert request.headers["OK-ACCESS-KEY"] == API_KEY
    assert request.headers["OK-ACCESS-PASSPHRASE"] == PASSPHRASE
    body = json.loads(request.content)
    assert body == {
        "instId": "BTC-USDT-SWAP",
        "tdMode": "cross",
        "clOrdId": "c1",
        "side": "buy",
        "posSide": "long",
        "ordType": "market",
        "sz": "100",
    }
    expected = sign_request(
        SECRET,
        timestamp=request.headers["OK-ACCESS-TIMESTAMP"],
        method="POST",
        request_path="/api/v5/trade/order",
        body=request.content.decode(),
    )
    assert request.headers["OK-ACCESS-SIGN"] == expected


async def test_upstream_error_code_surfaces() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "51000", "msg": "bad", "data": []})

    client = _client(handler)
    try:
        with pytest.raises(UpstreamError) as excinfo:
            await client.fetch_balance()
    finally:
        await client.aclose()
    assert excinfo.value.code == "51000"


async def test_fetch_positions_skips_zero_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": "0",
                "msg": "",
                "data": [
                    {"instId": "BTC-USDT-SWAP", "pos": "2", "posSide": "net", "avgPx": "100"},
                    {"instId": "ETH-USDT-SWAP", "pos": "0", "posSide": "net", "avgPx": "0"},
                ],
            },
        )

    client = _client(handler)
    try:
        positions = await client.fetch_positions()
    finally:
        await client.aclose()
    assert len(positions) == 1
    assert positions[0].position_side == "long"
    assert positions[0].quantity == Decimal("2")

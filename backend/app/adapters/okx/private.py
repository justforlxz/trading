"""OKX v5 私有 REST 适配器：签名、会话、下单/撤单/查单/成交/持仓/账户。

原始 JSON 只在本文件内出现，出口一律是 `app.ports.private` 的归一化 DTO。
签名与请求拼装是可单测的纯函数（`build_prehash` / `sign_request` /
`build_timestamp`），网络只经由注入的 `httpx` 传输层，测试用 `MockTransport`
即可断言「零真实网络」。

签名算法（OKX v5 文档）：`sign = base64(hmac_sha256(secret, prehash))`，
`prehash = timestamp + METHOD + requestPath + body`，其中 requestPath 含 query，
时间戳为毫秒精度 UTC ISO8601（`2020-12-08T09:08:57.715Z`）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

from app.adapters.okx.rate_limit import (
    OKX_RATE_LIMIT_CODES,
    RateLimitedError,
    RetryPolicy,
    TransientUpstreamError,
    UpstreamError,
    UpstreamUnavailable,
)
from app.ports.private import (
    AccountBalance,
    ExchangeFill,
    ExchangeOrder,
    ExchangePosition,
    OrderAck,
    OrderRequest,
)

USER_AGENT = "trading/0.1 (+https://github.com/justforlxz/trading)"
ZERO = Decimal("0")
SUCCESS_CODE = "0"

SIGNED_PATHS: dict[str, str] = {
    "place_order": "/api/v5/trade/order",
    "cancel_order": "/api/v5/trade/cancel-order",
    "fetch_order": "/api/v5/trade/order",
    "open_orders": "/api/v5/trade/orders-pending",
    "fills": "/api/v5/trade/fills",
    "positions": "/api/v5/account/positions",
    "balance": "/api/v5/account/balance",
}


def build_timestamp(moment: datetime) -> str:
    """UTC 毫秒精度 ISO8601；OKX 要求固定三位毫秒与 `Z` 后缀。"""

    aware = moment.astimezone(UTC)
    return aware.strftime("%Y-%m-%dT%H:%M:%S.") + f"{aware.microsecond // 1000:03d}Z"


def build_prehash(*, timestamp: str, method: str, request_path: str, body: str = "") -> str:
    """签名原文：`timestamp + METHOD + requestPath + body`（body 无则为空串）。"""

    return f"{timestamp}{method.upper()}{request_path}{body}"


def sign_request(
    secret: str, *, timestamp: str, method: str, request_path: str, body: str = ""
) -> str:
    """HMAC-SHA256 + Base64；返回请求头 `OK-ACCESS-SIGN` 的值。"""

    prehash = build_prehash(
        timestamp=timestamp, method=method, request_path=request_path, body=body
    )
    digest = hmac.new(secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def build_request_path(path: str, params: Mapping[str, Any] | None) -> str:
    """按传入顺序拼 query；空值参数不参与签名也不发送。"""

    if not params:
        return path
    filtered = [(key, value) for key, value in params.items() if value is not None]
    if not filtered:
        return path
    return f"{path}?{urlencode(filtered)}"


def to_exchange_size(quantity: Decimal, *, ct_val: Decimal, lot_sz: Decimal) -> Decimal:
    """基础币数量 → 合约张数：按 `ct_val` 折算并向下取整到 `lot_sz` 的整数倍。"""

    if ct_val <= ZERO:
        raise UpstreamError("missing_contract_size")
    if lot_sz <= ZERO:
        raise UpstreamError("missing_lot_size")
    contracts = quantity / ct_val
    steps = (contracts / lot_sz).to_integral_value(rounding="ROUND_FLOOR")
    size = steps * lot_sz
    if size <= ZERO:
        raise UpstreamError("size_below_minimum")
    return size


def _dec(value: Any) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def _text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _ts(value: Any) -> datetime:
    if value in (None, ""):
        return datetime.now(tz=UTC)
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def normalize_order(data: Mapping[str, Any]) -> ExchangeOrder:
    """OKX 订单字段 → 归一化快照。状态未知时保留原值，由调用方判错。"""

    pos_side = data.get("posSide") or "net"
    return ExchangeOrder(
        client_order_id=str(data.get("clOrdId") or ""),
        exchange_order_id=str(data.get("ordId") or ""),
        inst_id=str(data.get("instId") or ""),
        side=str(data.get("side") or ""),
        position_side=pos_side,
        state=str(data.get("state") or ""),
        quantity=_dec(data.get("sz")),
        filled_quantity=_dec(data.get("accFillSz")),
        average_price=_dec(data.get("avgPx")),
        fee=_dec(data.get("fee")),
        updated_at=_ts(data.get("uTime")),
    )


def normalize_fill(data: Mapping[str, Any]) -> ExchangeFill:
    return ExchangeFill(
        fill_id=str(data.get("fillId") or data.get("tradeId") or ""),
        client_order_id=(str(data["clOrdId"]) if data.get("clOrdId") else None),
        exchange_order_id=str(data.get("ordId") or ""),
        inst_id=str(data.get("instId") or ""),
        side=str(data.get("side") or ""),
        position_side=str(data.get("posSide") or "net"),
        quantity=_dec(data.get("fillSz")),
        price=_dec(data.get("fillPx")),
        fee=_dec(data.get("fee")),
        fee_currency=str(data.get("feeCcy") or ""),
        filled_at=_ts(data.get("ts")),
    )


def normalize_position(data: Mapping[str, Any]) -> ExchangePosition | None:
    """OKX 持仓 → long/short；`net` 模式按正负号拆方向。"""

    raw = _dec(data.get("pos"))
    if raw == ZERO:
        return None
    pos_side = str(data.get("posSide") or "net")
    if pos_side == "net":
        position_side = "long" if raw > ZERO else "short"
        quantity = abs(raw)
    else:
        position_side = pos_side
        quantity = abs(raw)
    return ExchangePosition(
        inst_id=str(data.get("instId") or ""),
        position_side=position_side,
        quantity=quantity,
        average_price=_dec(data.get("avgPx")),
        unrealized_pnl=_dec(data.get("upl")),
    )


class OkxPrivateClient:
    """OKX 私有接口客户端；`transport` 可注入，单测不产生真实网络。"""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str,
        api_secret: str,
        passphrase: str,
        contract_sizes: Mapping[str, Decimal] | None = None,
        lot_sizes: Mapping[str, Decimal] | None = None,
        timeout_seconds: float = 10.0,
        demo_trading: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 4,
        backoff_seconds: float = 0.5,
        retry: Any = None,
        sleep: Any = None,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._passphrase = passphrase
        self._contract_sizes = contract_sizes or {}
        self._lot_sizes = lot_sizes or {}
        self._retry = retry or RetryPolicy(
            max_retries=max_retries,
            base_delay=backoff_seconds,
            sleep=sleep,
        )
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if demo_trading:
            headers["x-simulated-trading"] = "1"
        self._client = httpx.AsyncClient(
            base_url=base_url, transport=transport, timeout=timeout_seconds, headers=headers
        )

    @property
    def attempts(self) -> int:
        return int(self._retry.attempts)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> OkxPrivateClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ 传输

    def _headers(self, *, method: str, request_path: str, body: str) -> dict[str, str]:
        timestamp = build_timestamp(datetime.now(tz=UTC))
        signature = sign_request(
            self._api_secret,
            timestamp=timestamp,
            method=method,
            request_path=request_path,
            body=body,
        )
        return {
            "OK-ACCESS-KEY": self._api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self._passphrase,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        request_path = build_request_path(path, params)
        body_text = json.dumps(body, separators=(",", ":"), ensure_ascii=False) if body else ""

        async def operation() -> list[dict[str, Any]]:
            headers = self._headers(method=method, request_path=request_path, body=body_text)
            response = await self._client.request(
                method,
                request_path,
                content=body_text.encode("utf-8") if body_text else None,
                headers=headers,
            )
            if response.status_code == 429:
                raise RateLimitedError("429")
            if response.status_code >= 500:
                raise TransientUpstreamError(str(response.status_code))
            try:
                payload = response.json()
            except ValueError as exc:
                raise UpstreamError("invalid_json") from exc
            code = str(payload.get("code", "-1"))
            if code in OKX_RATE_LIMIT_CODES:
                raise RateLimitedError(code)
            if code != SUCCESS_CODE:
                raise UpstreamError(str(payload.get("msg") or "okx error"), code=code)
            data = payload.get("data")
            return list(data) if isinstance(data, list) else []

        return await self._retry.run(operation)

    # ------------------------------------------------------------------ 交易

    async def place_order(self, request: OrderRequest) -> OrderAck:
        ct_val = self._contract_sizes.get(request.inst_id)
        if ct_val is None:
            raise UpstreamError("missing_contract_size")
        size = to_exchange_size(
            request.quantity,
            ct_val=ct_val,
            lot_sz=self._lot_sizes.get(request.inst_id, Decimal("1")),
        )
        body: dict[str, Any] = {
            "instId": request.inst_id,
            "tdMode": "cross",
            "clOrdId": request.client_order_id,
            "side": request.side,
            "posSide": request.position_side,
            "ordType": request.order_type,
            "sz": _text(size),
        }
        if request.order_type == "limit":
            if request.price is None:
                raise UpstreamError("missing_limit_price")
            body["px"] = _text(request.price)
        if request.reduce_only:
            body["reduceOnly"] = "true"

        data = await self._request("POST", SIGNED_PATHS["place_order"], body=body)
        if not data:
            raise UpstreamError("empty_order_ack")
        item = data[0]
        sub_code = str(item.get("sCode", SUCCESS_CODE))
        if sub_code != SUCCESS_CODE:
            raise UpstreamError(str(item.get("sMsg") or "okx order rejected"), code=sub_code)
        return OrderAck(
            client_order_id=str(item.get("clOrdId") or request.client_order_id),
            exchange_order_id=str(item.get("ordId") or ""),
            state="submitted",
            code=sub_code,
        )

    async def cancel_order(
        self,
        *,
        inst_id: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> None:
        body: dict[str, Any] = {"instId": inst_id}
        if exchange_order_id:
            body["ordId"] = exchange_order_id
        elif client_order_id:
            body["clOrdId"] = client_order_id
        else:
            raise UpstreamError("missing_order_reference")
        await self._request("POST", SIGNED_PATHS["cancel_order"], body=body)

    async def fetch_order(
        self,
        *,
        inst_id: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> ExchangeOrder | None:
        params: dict[str, Any] = {"instId": inst_id}
        if exchange_order_id:
            params["ordId"] = exchange_order_id
        elif client_order_id:
            params["clOrdId"] = client_order_id
        else:
            raise UpstreamError("missing_order_reference")
        data = await self._request("GET", SIGNED_PATHS["fetch_order"], params=params)
        return normalize_order(data[0]) if data else None

    async def list_open_orders(self, *, inst_id: str | None = None) -> list[ExchangeOrder]:
        params: dict[str, Any] = {"instType": "SWAP"}
        if inst_id:
            params["instId"] = inst_id
        data = await self._request("GET", SIGNED_PATHS["open_orders"], params=params)
        return [normalize_order(item) for item in data]

    async def fetch_fills(
        self, *, inst_id: str | None = None, since: datetime | None = None
    ) -> list[ExchangeFill]:
        params: dict[str, Any] = {"instType": "SWAP"}
        if inst_id:
            params["instId"] = inst_id
        if since is not None:
            params["begin"] = str(int(since.timestamp() * 1000))
        data = await self._request("GET", SIGNED_PATHS["fills"], params=params)
        return [normalize_fill(item) for item in data]

    async def fetch_positions(self) -> list[ExchangePosition]:
        data = await self._request("GET", SIGNED_PATHS["positions"], params={"instType": "SWAP"})
        positions = (normalize_position(item) for item in data)
        return [item for item in positions if item is not None]

    async def fetch_balance(self) -> AccountBalance:
        data = await self._request("GET", SIGNED_PATHS["balance"], params={"ccy": "USDT"})
        if not data:
            raise UpstreamError("empty_balance")
        item = data[0]
        available = ZERO
        for detail in item.get("details") or []:
            available += _dec(detail.get("availEq") or detail.get("availBal"))
        return AccountBalance(
            total_equity=_dec(item.get("totalEq")),
            available_equity=available,
            currency="USDT",
        )


__all__ = [
    "OkxPrivateClient",
    "UpstreamUnavailable",
    "build_prehash",
    "build_request_path",
    "build_timestamp",
    "normalize_fill",
    "normalize_order",
    "normalize_position",
    "sign_request",
    "to_exchange_size",
]

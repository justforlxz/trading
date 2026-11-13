"""假 OKX 的交易域：账户余额、持仓、订单、成交与私有接口鉴权。

交易域与行情域共用同一份内存数据源，但**错误形态必须和真实上游一致**，否则适配
层里那些错误分支就只是在跟假实现对话：

- 业务错误走 HTTP 200 + 非零 `code`（例如 SPOT 查持仓接口不支持 = `51000`）。
- 单张订单的失败走 `code: "1"` + `data[0].sCode`（例如余额不足 = `51008`、
  同一 `clOrdId` 重复 = `51016`、订单不存在 = `51603`）。
- 鉴权失败走 HTTP 401 + `50113`（签名不对）/ `50103`（Key 不对）/ `50105`（口令不对）。

**参数校验按类别分开**，与真实上游一致：现货带 `posSide` / `reduceOnly` / `lever` /
`mgnMode` 一律判参数错误（`51000`），永续的 `tdMode` 只能是 `cross` / `isolated`。
适配层如果偷偷把空参数塞进请求，这里立刻红。

签名校验是**独立实现**（`expected_sign`）：它不复用被测的 `app.exchange.okx.sign`，
否则「签名算错了」和「校验也按错的算」会互相掩盖。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

UNKNOWN_INST_ID_CODE = "51001"
INVALID_PARAMETER_CODE = "51000"
DUPLICATE_CLIENT_ORDER_ID_CODE = "51016"
ORDER_NOT_FOUND_CODE = "51603"
INSUFFICIENT_BALANCE_CODE = "51008"
ORDER_CANNOT_BE_CANCELED_CODE = "51400"

INVALID_SIGN_STATUS = 401
INVALID_SIGN_CODE = "50113"
INVALID_KEY_CODE = "50103"
INVALID_PASSPHRASE_CODE = "50105"

#: 逐单失败的封包码：顶层 `code` 是 "1"，具体原因在 `data[0].sCode`。
ORDER_FAILED_CODE = "1"

SUPPORTED_TD_MODES: dict[str, frozenset[str]] = {
    "SPOT": frozenset({"cash"}),
    "SWAP": frozenset({"cross", "isolated"}),
}
#: 只属于永续的下单参数。现货请求里出现任何一个都判参数错误。
SWAP_ONLY_PARAMS: tuple[str, ...] = ("posSide", "reduceOnly", "lever", "mgnMode")
POS_SIDES = frozenset({"long", "short", "net"})
#: 上游对 `clOrdId` 的要求：1..32 位字母数字（连字符会被判参数错误）。
CLIENT_ORDER_ID_PATTERN = re.compile(r"[0-9A-Za-z]{1,32}")


@dataclass(frozen=True, slots=True)
class FakeCredentials:
    """假交易所认的凭据（与真实凭据无关，测试专用）。"""

    api_key: str = "fake-api-key"
    secret: str = "test-secret"
    passphrase: str = "fake-passphrase"


class OkxAuthError(Exception):
    """鉴权失败：HTTP 4xx + 非零 `code`。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class OkxOrderError(Exception):
    """逐单失败：HTTP 200 + `code: "1"` + `data[0].sCode`。"""

    def __init__(self, s_code: str, message: str) -> None:
        super().__init__(message)
        self.s_code = s_code
        self.message = message


def expected_sign(
    secret: str,
    *,
    timestamp: str,
    method: str,
    request_path: str,
    body: str,
) -> str:
    """独立实现的签名：`Base64(HMAC-SHA256(secret, timestamp + method + path + body))`。"""

    message = f"{timestamp}{method.upper()}{request_path}{body}"
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def verify_request(
    *,
    headers: dict[str, str],
    method: str,
    path: str,
    query: str,
    body: str,
    credentials: FakeCredentials,
) -> None:
    """按真实上游的口径校验签名头；任何一项不符都抛 `OkxAuthError`。"""

    lowered = {name.lower(): value for name, value in headers.items()}
    api_key = lowered.get("ok-access-key")
    if not api_key:
        raise OkxAuthError(INVALID_SIGN_CODE, "Missing OK-ACCESS-KEY header")
    if api_key != credentials.api_key:
        raise OkxAuthError(INVALID_KEY_CODE, "Invalid OK-ACCESS-KEY")
    if lowered.get("ok-access-passphrase") != credentials.passphrase:
        raise OkxAuthError(INVALID_PASSPHRASE_CODE, "Invalid OK-ACCESS-PASSPHRASE")
    timestamp = lowered.get("ok-access-timestamp")
    if not timestamp:
        raise OkxAuthError(INVALID_SIGN_CODE, "Missing OK-ACCESS-TIMESTAMP header")
    simulated = lowered.get("x-simulated-trading")
    if simulated is not None and simulated != "1":
        raise OkxAuthError(INVALID_SIGN_CODE, "Invalid x-simulated-trading header")

    request_path = f"{path}?{query}" if query else path
    expected = expected_sign(
        credentials.secret,
        timestamp=timestamp,
        method=method,
        request_path=request_path,
        body=body,
    )
    if lowered.get("ok-access-sign") != expected:
        raise OkxAuthError(INVALID_SIGN_CODE, "Invalid OK-ACCESS-SIGN")


class TradeBook:
    """假交易所的交易域内存状态。

    确定性优先：订单号与成交号是自增序号，成交价由调用方预置的标的价格决定，
    没有随机数与时钟抖动，同一次调用序列必然得到同一份结果。
    """

    def __init__(
        self,
        *,
        credentials: FakeCredentials | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.credentials = credentials or FakeCredentials()
        self._clock = clock
        self._balances: dict[str, dict[str, str]] = {}
        self._positions: list[dict[str, str]] = []
        self._orders: dict[str, dict[str, str]] = {}
        self._order_ids: dict[tuple[str, str], str] = {}
        self._fills: list[dict[str, str]] = []
        self._marks: dict[str, str] = {}
        self._sequence = 0
        #: 私有接口的调用记录：`(method, path, query, body)`，供用例断言调用形态。
        self.requests: list[tuple[str, str, str, str]] = []
        #: 下单前回调：用来证明「请求到达上游时，本地登记已经落库」。
        self.on_before_order: Callable[[dict[str, Any]], None] | None = None

    # ------------------------------------------------------------------ 预置状态

    def set_balance(
        self,
        currency: str,
        *,
        available: str,
        frozen: str = "0",
        avg_price: str = "",
        upl: str = "0",
    ) -> None:
        self._balances[currency] = {
            "ccy": currency,
            "availBal": available,
            "frozenBal": frozen,
            "avgPx": avg_price,
            "upl": upl,
        }

    def set_position(
        self,
        inst_id: str,
        *,
        qty: str,
        pos_side: str,
        avg_price: str,
        upl: str = "0",
    ) -> None:
        self._positions.append(
            {
                "instId": inst_id,
                "pos": qty,
                "posSide": pos_side,
                "avgPx": avg_price,
                "upl": upl,
                "mgnMode": "cross",
            }
        )

    def set_mark_price(self, inst_id: str, price: str) -> None:
        """预置成交价：市价单按这个价格成交，限价单永远挂着等撤单。"""

        self._marks[inst_id] = price

    def fill_order(self, order_id: str, *, qty: str, price: str) -> None:
        """给一张挂单补一笔成交；可以多次调用，成交量逐笔累加。

        真实上游的限价单不会「一挂就全成」，部分成交后状态是 `partially_filled`，
        剩下一部分继续挂着。这里按同样的口径更新 `accFillSz` / `state` / `avgPx`
        并写入一条成交记录，供恢复与对账用例走完整链路。
        """

        order = self._orders.get(order_id)
        if order is None:
            raise OkxOrderError(ORDER_NOT_FOUND_CODE, f"Order does not exist: {order_id}")
        if order["state"] not in {"live", "partially_filled"}:
            raise OkxOrderError(
                ORDER_CANNOT_BE_CANCELED_CODE,
                f"Order is already {order['state']}: {order_id}",
            )
        remaining = Decimal(order["sz"]) - Decimal(order["accFillSz"])
        fill_qty = Decimal(qty)
        if fill_qty <= 0 or fill_qty > remaining:
            raise OkxOrderError(
                INVALID_PARAMETER_CODE,
                f"Parameter fill size error: {qty} (remaining {remaining})",
            )
        filled = Decimal(order["accFillSz"]) + fill_qty
        previous = [row for row in self._fills if row["ordId"] == order_id]
        total_cost = sum(
            (Decimal(row["fillSz"]) * Decimal(row["fillPx"]) for row in previous),
            Decimal(0),
        ) + fill_qty * Decimal(price)
        order["accFillSz"] = format(filled, "f")
        order["avgPx"] = format(total_cost / filled, "f")
        order["state"] = "filled" if filled == Decimal(order["sz"]) else "partially_filled"
        order["uTime"] = self._now_millis()
        self.add_fill(
            inst_id=order["instId"],
            order_id=order_id,
            qty=qty,
            price=price,
            side=order["side"],
        )

    def add_fill(
        self,
        *,
        inst_id: str,
        order_id: str,
        qty: str,
        price: str,
        side: str = "buy",
        fee: str = "0",
        fee_ccy: str = "USDT",
    ) -> None:
        self._fills.append(
            {
                "tradeId": self._next_id("trade"),
                "ordId": order_id,
                "instId": inst_id,
                "side": side,
                "fillSz": qty,
                "fillPx": price,
                "fee": fee,
                "feeCcy": fee_ccy,
                "ts": self._now_millis(),
            }
        )

    @property
    def order_count(self) -> int:
        """上游侧已存在的订单条数：幂等用例直接断言它。"""

        return len(self._orders)

    # ------------------------------------------------------------------ 查询接口

    def balance(self, ccy: str) -> dict[str, Any]:
        details = [
            detail for name, detail in sorted(self._balances.items()) if not ccy or name == ccy
        ]
        return {"details": [dict(detail) for detail in details], "totalEq": "0"}

    def positions(self, inst_type: str) -> list[dict[str, str]]:
        if inst_type not in SUPPORTED_TD_MODES:
            raise OkxOrderError(INVALID_PARAMETER_CODE, f"Parameter instType error: {inst_type!r}")
        if inst_type == "SPOT":
            # 真实上游：现货没有持仓接口，直接判参数错误。
            raise OkxOrderError(INVALID_PARAMETER_CODE, f"Parameter instType error: {inst_type}")
        return [dict(row) for row in self._positions]

    def order(self, *, inst_id: str, ord_id: str = "", client_order_id: str = "") -> dict[str, str]:
        if ord_id:
            row = self._orders.get(ord_id)
        elif client_order_id:
            found = self._order_ids.get((inst_id, client_order_id))
            row = self._orders.get(found) if found is not None else None
        else:
            raise OkxOrderError(INVALID_PARAMETER_CODE, "Parameter ordId or clOrdId is required")
        if row is None:
            raise OkxOrderError(
                ORDER_NOT_FOUND_CODE,
                f"Order does not exist: {ord_id or client_order_id}",
            )
        return dict(row)

    def fills(self, *, inst_id: str, ord_id: str = "") -> list[dict[str, str]]:
        return [
            dict(row)
            for row in self._fills
            if row["instId"] == inst_id and (not ord_id or row["ordId"] == ord_id)
        ]

    # ------------------------------------------------------------------ 交易接口

    def place(self, body: dict[str, Any], *, inst_type: str) -> dict[str, str]:
        if self.on_before_order is not None:
            self.on_before_order(body)
        self._validate_order(body, inst_type=inst_type)

        client_order_id = str(body.get("clOrdId") or "")
        if client_order_id and (body["instId"], client_order_id) in self._order_ids:
            raise OkxOrderError(
                DUPLICATE_CLIENT_ORDER_ID_CODE,
                f"Duplicated clOrdId: {client_order_id}",
            )
        order = self._build_order(body, inst_type=inst_type)
        self._orders[order["ordId"]] = order
        if client_order_id:
            self._order_ids[(order["instId"], client_order_id)] = order["ordId"]
        return dict(order)

    def cancel(self, body: dict[str, Any]) -> dict[str, str]:
        ord_id = str(body.get("ordId") or "")
        order = self._orders.get(ord_id)
        if order is None:
            raise OkxOrderError(ORDER_NOT_FOUND_CODE, f"Order does not exist: {ord_id}")
        if order["state"] != "live":
            raise OkxOrderError(
                ORDER_CANNOT_BE_CANCELED_CODE,
                f"Order is already {order['state']}: {ord_id}",
            )
        order["state"] = "canceled"
        order["uTime"] = self._now_millis()
        return {"ordId": ord_id, "clOrdId": order["clOrdId"]}

    # ------------------------------------------------------------------ 内部

    def _validate_order(self, body: dict[str, Any], *, inst_type: str) -> None:
        inline = " ".join(f"{key}={value}" for key, value in sorted(body.items()))
        for field in ("instId", "side", "ordType", "sz"):
            if not str(body.get(field) or ""):
                raise OkxOrderError(INVALID_PARAMETER_CODE, f"Parameter {field} error: {inline}")
        client_order_id = str(body.get("clOrdId") or "")
        if client_order_id and CLIENT_ORDER_ID_PATTERN.fullmatch(client_order_id) is None:
            raise OkxOrderError(
                INVALID_PARAMETER_CODE, f"Parameter clOrdId error: {client_order_id}"
            )
        if str(body["side"]) not in {"buy", "sell"}:
            raise OkxOrderError(INVALID_PARAMETER_CODE, f"Parameter side error: {inline}")
        if str(body["ordType"]) not in {"market", "limit"}:
            raise OkxOrderError(INVALID_PARAMETER_CODE, f"Parameter ordType error: {inline}")
        if inst_type == "SPOT":
            for field in SWAP_ONLY_PARAMS:
                if field in body:
                    raise OkxOrderError(
                        INVALID_PARAMETER_CODE,
                        f"Parameter {field} error: 现货下单不接受 {field}",
                    )
        pos_side = body.get("posSide")
        if pos_side is not None and str(pos_side) not in POS_SIDES:
            raise OkxOrderError(INVALID_PARAMETER_CODE, f"Parameter posSide error: {inline}")
        td_mode = str(body.get("tdMode") or "")
        if td_mode not in SUPPORTED_TD_MODES[inst_type]:
            raise OkxOrderError(INVALID_PARAMETER_CODE, f"Parameter tdMode error: {inline}")
        if str(body["ordType"]) == "limit" and not str(body.get("px") or ""):
            raise OkxOrderError(INVALID_PARAMETER_CODE, f"Parameter px error: {inline}")
        if str(body["ordType"]) == "market" and str(body.get("px") or ""):
            raise OkxOrderError(INVALID_PARAMETER_CODE, f"Parameter px error: {inline}")
        if inst_type == "SPOT":
            self._require_affordable(body)

    def _require_affordable(self, body: dict[str, Any]) -> None:
        """现货买单按名义金额与可用 USDT 比较：不够就按真实上游的 51008 拒单。

        永续的保证金校验不在假实现里模拟：它要按杠杆与维持保证金算，属于 T6.1 的
        范围，这里只覆盖「现金不够买现货」这一条确定性判据。
        """

        if str(body["side"]) != "buy":
            return
        price = str(body.get("px") or self._marks.get(str(body["instId"]), ""))
        if not price:
            return
        notional = float(body["sz"]) * float(price)
        available = float(self._balances.get("USDT", {}).get("availBal", "0"))
        if notional > available:
            raise OkxOrderError(
                INSUFFICIENT_BALANCE_CODE,
                "Order failed. Insufficient USDT balance",
            )

    def _build_order(self, body: dict[str, Any], *, inst_type: str) -> dict[str, str]:
        now = self._now_millis()
        order = {
            "ordId": self._next_id("ord"),
            "clOrdId": str(body.get("clOrdId") or ""),
            "instId": str(body["instId"]),
            "side": str(body["side"]),
            "ordType": str(body["ordType"]),
            "sz": str(body["sz"]),
            "px": str(body.get("px") or ""),
            "accFillSz": "0",
            "state": "live",
            "cTime": now,
            "uTime": now,
            "instType": inst_type,
        }
        if inst_type == "SPOT" and order["ordType"] == "market":
            self._fill_market_order(order)
        return order

    def _fill_market_order(self, order: dict[str, str]) -> None:
        price = self._marks.get(order["instId"], "0")
        order["accFillSz"] = order["sz"]
        order["state"] = "filled"
        order["avgPx"] = price
        self.add_fill(
            inst_id=order["instId"],
            order_id=order["ordId"],
            qty=order["sz"],
            price=price,
            side=order["side"],
        )

    def _next_id(self, prefix: str) -> str:
        self._sequence += 1
        return f"{prefix}-{self._sequence}"

    def _now_millis(self) -> str:
        return str(int(self._clock() * 1000))

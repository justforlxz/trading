"""OKX 私有交易接口 → `TradePort` 实现。

本模块只做三件事：把意图翻译成上游参数、把上游应答翻译成 `core` 的值对象、按
`clientOrderId` 保证重复提交只产生一张单。业务判断（仓位、风控、目标组合）不在这里。

两处**按类别分叉**，各自只有一处：

1. 下单参数：`_order_body` 是全仓唯一一处按类别选择参数集的地方。现货与永续各有一
   份构造参数集的函数，现货那份里根本没有 `posSide` / `reduceOnly` —— 不是「都带上、
   空值就忽略」，因为上游会把空字符串当成非法取值直接拒单。
2. 持仓来源：永续读 `/account/positions`，现货该接口返回 `51000`（不支持），只能由
   余额明细推导。走哪条由标的模块的 `TradingRules.has_position_endpoint` 决定，
   适配层不自己判类别；两条路径都产出 `core.Position`，字段集合因此天然一致。

现货持仓的口径（T6.3 对账要按这三条比，别处不许另立一套）：

- 持仓量 `qty` = `availBal`（可用量）+ `frozenBal`（冻结量），恒为正。
- 成本价 `avg_price` = 上游 `avgPx`；纯现货现金余额上游不下发这个字段，此时记 0，
  表示「成本未知」，不拿现价冒充。
- 未实现盈亏 `unrealized_pnl` = 上游 `upl`，计价币是标的的报价币。

幂等：`clientOrderId` 在**发请求之前**写进 `order_submissions`（见 `ledger`）。重发
同一个键时先查本地登记、再查上游有没有这张单，确认没有才会重发，因此断电重发不会
产生第二张单。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings, get_settings
from app.core import (
    AccountSnapshot,
    Clock,
    DataUnavailable,
    ExchangePosition,
    ExecutionRejected,
    Fill,
    Money,
    Order,
    OrderIntent,
    Position,
    SystemClock,
    TradePort,
    ValidationError,
    utc_from_millis,
)
from app.exchange.errors import ExchangeError
from app.exchange.okx.client import OkxClient
from app.exchange.okx.ledger import (
    claim_submission,
    load_submission,
    mark_rejected,
    mark_submitted,
    reopen_submission,
)
from app.exchange.okx.sign import iso_timestamp, require_credentials, sign_headers
from app.exchange.okx.snapshots import parse_exchange_position_row
from app.instrument import (
    DEFAULT_QUOTE_CURRENCY,
    Instrument,
    list_instruments,
    spot_currency,
    trading_categories,
    trading_rules,
)

__all__ = ["SETTLE_CURRENCY", "OkxPrivateClient", "create_trade_port"]

_BALANCE_PATH = "/api/v5/account/balance"
_POSITIONS_PATH = "/api/v5/account/positions"
_ORDER_PATH = "/api/v5/trade/order"
_CANCEL_ORDER_PATH = "/api/v5/trade/cancel-order"
_FILLS_PATH = "/api/v5/trade/fills"

#: 下单与撤单接口的「逐单失败」封包码：`code` 是 "1"，真实原因在 `data[0].sCode`。
ORDER_FAILURE_CODES: frozenset[str] = frozenset({"1"})
#: 上游返回码：`clientOrderId` 已存在（同一个键已经下过单）。
DUPLICATE_CLIENT_ORDER_ID = "51016"
#: 上游返回码：订单不存在（用于「这张单到底发出去没有」的判断）。
ORDER_NOT_FOUND = "51603"

#: 项目只接 USDT 本位永续，未实现盈亏的计价币就是 USDT。
SETTLE_CURRENCY = "USDT"
#: 永续下单的保证金模式：本项目只做全仓（逐仓属于账户设置，不在意图里）。
SWAP_TD_MODE = "cross"
#: 现货下单的保证金模式：现货只有现金模式，取值与永续完全不同。
SPOT_TD_MODE = "cash"
#: 永续意图没给持仓方向时的默认值：单向持仓模式。
DEFAULT_POS_SIDE = "net"
#: 上游对 `clOrdId` 的要求：1..32 位字母数字，**不接受连字符与下划线**
#: （实测 `clOrdId=idem-1` 会回 51000 Parameter clOrdId error）。
_CLIENT_ORDER_ID = re.compile(r"[0-9A-Za-z]{1,32}")

_ORDER_QUERY_MAX = 100


class OkxPrivateClient(TradePort):
    """基于 OKX 私有 REST 的交易端口实现。

    凭据只经 `Settings` 注入，本类不读环境变量以外的来源；`clock` 可注入，用于
    让签名时间戳在测试里可复现。私有接口依赖标的表：`inst_id → 类别` 的解析与
    现货持仓的 `币种 → instId` 映射都取自 `app.instrument`，不在适配层拼字符串。
    """

    def __init__(
        self,
        client: OkxClient,
        *,
        settings: Settings | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._client = client
        self._settings = settings or get_settings()
        self._clock = clock or SystemClock()
        require_credentials(self._settings)

    # ---------------------------------------------------------------- 资金与持仓

    def balance(self, currency: str = "USDT") -> Money:
        """指定币种的可用余额；账户里没有该币种时记 0（不是错误）。"""

        rows = self._get(_BALANCE_PATH, {"ccy": currency})
        details = _details(rows)
        for detail in details:
            if str(detail.get("ccy") or "") == currency:
                available = detail.get("availBal") or detail.get("availEq") or "0"
                return Money(_decimal(available), currency)
        return Money(Decimal(0), currency)

    def positions(self) -> list[Position]:
        """当前持仓（无持仓的标的不出现）；两个类别的来源不同，形状相同。

        要查哪些类别取自类别规则表，**不是**取自库里同步到哪些标的：用标的表推类别，
        库里只同步到一类时会静默少查一类持仓，看起来就像「本来没有持仓」。
        标的表为空说明还没同步标的，现货持仓的币种对不回 `instId`，此时明确报错。
        """

        instruments = list_instruments()
        if not instruments:
            raise DataUnavailable("标的表为空, 先同步标的再查持仓")
        products_by_category = _products_by_category(instruments)
        held: list[Position] = []
        for inst_type in trading_categories():
            if trading_rules(inst_type).has_position_endpoint:
                held += self._endpoint_positions(inst_type)
            else:
                held += self._balance_positions(products_by_category.get(inst_type, {}))
        return held

    def account_snapshot(self, currency: str = SETTLE_CURRENCY) -> AccountSnapshot:
        """账户权益只读快照；不涉及任何下单、撤单或平仓接口。

        上游在 `/account/balance` 同时给出账户级字段（`totalEq` / `imr` / `upl`）
        与币种明细（`cashBal` / `availEq`）。保证金使用率不直接采用 `mgnRatio`
        （那是维持保证金率），而是按项目统一口径
        `已用保证金 / (已用保证金 + 可用保证金)` 计算；只有在上游没有给出
        `imr` 与可用权益时，才把 0 到 1 之间的 `mgnRatio` 当作兜底。
        """

        rows = self._get(_BALANCE_PATH, {"ccy": currency})
        top = _first_row(rows, action="账户余额")
        detail = _currency_detail(rows, currency)

        equity = _decimal_or_zero(top.get("totalEq"), top.get("adjEq"))
        used_margin = _decimal_or_zero(top.get("imr"))
        available_equity = _decimal_or_none(top.get("availEq"))
        if available_equity is None:
            available_equity = _decimal_or_none(detail.get("availEq"))
        if available_equity is None:
            available_equity = equity - used_margin
        cash_balance = _decimal_or_zero(detail.get("cashBal"))
        unrealized_pnl = _decimal_or_zero(top.get("upl"), detail.get("upl"))
        fallback_ratio = _decimal_or_none(top.get("mgnRatio"))
        margin_ratio = _margin_usage_ratio(used_margin, available_equity, fallback_ratio)

        return AccountSnapshot(
            currency=currency,
            equity=equity,
            available_equity=available_equity,
            cash_balance=cash_balance,
            unrealized_pnl=unrealized_pnl,
            used_margin=used_margin,
            available_margin=available_equity,
            margin_ratio=margin_ratio,
        )

    def position_snapshots(self) -> list[ExchangePosition]:
        """交易所侧持仓的只读快照：永续读 `/account/positions`，现货由余额推导。

        类别差异仍由标的模块的 `TradingRules.has_position_endpoint` 决定，本方法
        不自行判断 `SPOT` / `SWAP`。现货没有上游 `posId`，用
        `inst_id + ":" + side` 生成稳定值；杠杆、标记价、强平价与保证金对现货均为
        `None`，不填 0 冒充。
        """

        instruments = list_instruments()
        if not instruments:
            raise DataUnavailable("标的表为空, 先同步标的再查持仓")
        products_by_category = _products_by_category(instruments)
        held: list[ExchangePosition] = []
        for inst_type in trading_categories():
            if trading_rules(inst_type).has_position_endpoint:
                held += self._endpoint_position_snapshots(inst_type)
            else:
                held += self._balance_position_snapshots(products_by_category.get(inst_type, {}))
        return held

    # -------------------------------------------------------------------- 交易

    def place(self, intent: OrderIntent) -> Order:
        """按意图下单；同一个 `clientOrderId` 重复提交只产生一张上游单。"""

        body = _order_body(intent, inst_type=self._inst_type(intent.inst_id))
        if not intent.client_order_id:
            return self._submit(body, intent)
        if not claim_submission(intent, now=self._clock.now()):
            return self._replay(body, intent)
        return self._submit_claimed(body, intent)

    def cancel(self, inst_id: str, order_id: str) -> None:
        """撤单；上游拒撤（已成交、已撤销、不存在）抛 `ExecutionRejected`。"""

        rows = self._post(
            _CANCEL_ORDER_PATH,
            {"instId": inst_id, "ordId": order_id},
            tolerate=ORDER_FAILURE_CODES,
        )
        _require_order_accepted(rows, action="撤单")

    def order(self, inst_id: str, order_id: str) -> Order:
        """按上游订单号查单。"""

        return self._get_order(inst_id, {"ordId": order_id})

    def fills(self, inst_id: str, order_id: str | None = None) -> list[Fill]:
        """查询成交；给出 `order_id` 时只返回这张单的成交。"""

        params = {"instId": inst_id}
        if order_id is not None:
            params["ordId"] = order_id
        params["limit"] = str(_ORDER_QUERY_MAX)
        return [_parse_fill(row) for row in self._get(_FILLS_PATH, params)]

    def close(self) -> None:
        """释放底层连接。"""

        self._client.close()

    def __enter__(self) -> OkxPrivateClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -------------------------------------------------------------------- 内部

    def _submit(self, body: dict[str, str], intent: OrderIntent) -> Order:
        row = _first_row(
            self._post(_ORDER_PATH, body, tolerate=ORDER_FAILURE_CODES),
            action="下单",
        )
        if str(row.get("sCode") or "0") != "0":
            duplicate = str(row.get("sCode")) == DUPLICATE_CLIENT_ORDER_ID
            if duplicate and intent.client_order_id:
                existing = self._order_by_client_id(intent.inst_id, intent.client_order_id)
                if existing is not None:
                    _require_same_intent(
                        intent,
                        inst_id=existing.inst_id,
                        side=existing.side,
                        order_type=existing.order_type,
                        qty=existing.qty,
                        price=existing.price,
                    )
                    return existing
            reason = row.get("sMsg") or "未给出原因"
            raise ExecutionRejected(f"上游拒单 {row.get('sCode')}:{reason}")
        order_id = str(row.get("ordId") or "")
        if not order_id:
            raise ExchangeError("下单应答缺少订单号")
        return self._get_order(intent.inst_id, {"ordId": order_id})

    def _submit_claimed(self, body: dict[str, str], intent: OrderIntent) -> Order:
        try:
            order = self._submit(body, intent)
        except ExecutionRejected:
            mark_rejected(intent.client_order_id, now=self._clock.now())
            raise
        mark_submitted(intent.client_order_id, order.order_id, now=self._clock.now())
        return order

    def _replay(self, body: dict[str, str], intent: OrderIntent) -> Order:
        """重复提交同一个 `clientOrderId`：先确认上游到底有没有这张单。

        同一个幂等键只对应一个意图：换了标的、方向或数量还用同一个键，就是调用方拿错
        了键。此时返回旧订单会让调用方以为新单已经下出去，必须报错。
        """

        record = load_submission(intent.client_order_id)
        if record is not None and record.order_id:
            _require_same_intent(
                intent,
                inst_id=record.inst_id,
                side=record.side,
                order_type=record.order_type,
                qty=record.qty,
                price=record.price,
            )
            return self._get_order(record.inst_id, {"ordId": record.order_id})
        existing = self._order_by_client_id(intent.inst_id, intent.client_order_id)
        if existing is not None:
            _require_same_intent(
                intent,
                inst_id=existing.inst_id,
                side=existing.side,
                order_type=existing.order_type,
                qty=existing.qty,
                price=existing.price,
            )
            mark_submitted(intent.client_order_id, existing.order_id, now=self._clock.now())
            return existing
        # 上游确实没有这张单（上一次在发出去之前就中断了），此时重发是安全的。
        if record is None:
            claim_submission(intent, now=self._clock.now())
        else:
            reopen_submission(intent.client_order_id, now=self._clock.now())
        return self._submit_claimed(body, intent)

    def _order_by_client_id(self, inst_id: str, client_order_id: str) -> Order | None:
        try:
            return self._get_order(inst_id, {"clOrdId": client_order_id})
        except ExchangeError as exc:
            if exc.code == ORDER_NOT_FOUND:
                return None
            raise

    def _get_order(self, inst_id: str, selector: dict[str, str]) -> Order:
        rows = self._get(_ORDER_PATH, {"instId": inst_id, **selector})
        return _parse_order(_first_row(rows, action=f"查询订单 {inst_id}"))

    def _endpoint_positions(self, inst_type: str) -> list[Position]:
        """永续（有持仓接口的类别）：直接读上游持仓。"""

        held: list[Position] = []
        for row in self._get(_POSITIONS_PATH, {"instType": inst_type}):
            qty = _signed_qty(row)
            if qty == 0:
                continue
            held.append(
                Position(
                    inst_id=str(row["instId"]),
                    qty=qty,
                    avg_price=_decimal(row.get("avgPx") or "0"),
                    unrealized_pnl=Money(_decimal(row.get("upl") or "0"), SETTLE_CURRENCY),
                )
            )
        return held

    def _balance_positions(self, products: dict[str, tuple[str, str]]) -> list[Position]:
        """现货（没有持仓接口的类别）：由余额明细推导，口径见模块文档。"""

        held: list[Position] = []
        for detail in _details(self._get(_BALANCE_PATH, None)):
            product = products.get(str(detail.get("ccy") or ""))
            if product is None:
                continue
            inst_id, quote_ccy = product
            qty = _decimal(detail.get("availBal") or "0") + _decimal(detail.get("frozenBal") or "0")
            if qty == 0:
                continue
            held.append(
                Position(
                    inst_id=inst_id,
                    qty=qty,
                    avg_price=_decimal(detail.get("avgPx") or "0"),
                    unrealized_pnl=Money(_decimal(detail.get("upl") or "0"), quote_ccy),
                )
            )
        return held

    def _endpoint_position_snapshots(self, inst_type: str) -> list[ExchangePosition]:
        """有持仓接口的类别：把上游整行映射成只读快照。"""

        held: list[ExchangePosition] = []
        for row in self._get(_POSITIONS_PATH, {"instType": inst_type}):
            pos = _decimal(row.get("pos") or "0")
            if pos == 0:
                continue
            held.append(parse_exchange_position_row(row))
        return held

    def _balance_position_snapshots(
        self, products: dict[str, tuple[str, str]]
    ) -> list[ExchangePosition]:
        """没有持仓接口的类别：由余额明细推导，缺失字段如实留空。"""

        held: list[ExchangePosition] = []
        for detail in _details(self._get(_BALANCE_PATH, None)):
            product = products.get(str(detail.get("ccy") or ""))
            if product is None:
                continue
            inst_id, _quote_ccy = product
            qty = _decimal(detail.get("availBal") or "0") + _decimal(detail.get("frozenBal") or "0")
            if qty == 0:
                continue
            held.append(
                ExchangePosition(
                    pos_id=f"{inst_id}:long",
                    inst_id=inst_id,
                    pos_side="long",
                    size=qty,
                    avg_px=_decimal(detail.get("avgPx") or "0"),
                    mark_px=None,
                    upl=_decimal_or_none(detail.get("upl")),
                    upl_ratio=None,
                    lever=None,
                    mgn_mode=None,
                    liq_px=None,
                    margin=None,
                )
            )
        return held

    def _inst_type(self, inst_id: str) -> str:
        """实例 → 类别；只查标的表，不拆 `instId` 字符串。"""

        for row in list_instruments():
            if row.symbol == inst_id:
                return row.inst_type
        raise ValidationError(f"标的 {inst_id} 不在标的表里, 先同步标的再下单")

    def _get(self, path: str, params: dict[str, str] | None) -> list[Any]:
        target, headers = self._signed("GET", path, params)
        return self._client.get(target, headers=headers)

    def _post(
        self,
        path: str,
        payload: dict[str, str],
        *,
        tolerate: frozenset[str] = frozenset(),
    ) -> list[Any]:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        target, headers = self._signed("POST", path, body=body)
        return self._client.post(target, content=body, headers=headers, tolerate=tolerate)

    def _signed(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        *,
        body: str = "",
    ) -> tuple[str, dict[str, str]]:
        """算好「要发的路径」与「签名头」：签名串与真实路径由同一个 `target` 派生。"""

        query = urlencode(params) if params else ""
        target = f"{path}?{query}" if query else path
        headers = sign_headers(
            api_key=self._settings.okx_api_key,
            secret=self._settings.okx_secret_key,
            passphrase=self._settings.okx_passphrase,
            timestamp=iso_timestamp(self._clock.now()),
            method=method,
            request_path=target,
            body=body,
            demo=self._settings.okx_demo,
        )
        return target, headers


def create_trade_port(
    *,
    settings: Settings | None = None,
    transport: httpx.BaseTransport | None = None,
    clock: Clock | None = None,
) -> OkxPrivateClient:
    """按进程配置装配私有交易端口；`transport` 供本地联调与测试注入。"""

    return OkxPrivateClient(
        OkxClient(settings=settings, transport=transport),
        settings=settings,
        clock=clock,
    )


def _order_body(intent: OrderIntent, *, inst_type: str) -> dict[str, str]:
    """下单参数分叉：全仓唯一一处按类别选择参数集的地方。"""

    rules = trading_rules(inst_type)  # 未注册的类别在这里报错，不靠猜
    body = {
        "instId": intent.inst_id,
        "side": intent.side,
        "ordType": intent.order_type,
        "sz": format(intent.qty, "f"),
    }
    if intent.client_order_id:
        _require_client_order_id(intent.client_order_id)
        body["clOrdId"] = intent.client_order_id
    if intent.price is not None:
        body["px"] = format(intent.price, "f")
    if inst_type == "SPOT":
        body.update(_spot_order_params(intent))
    elif rules.has_margin:
        body.update(_swap_order_params(intent))
    else:
        # 新增一个既不是现货、又没有保证金的类别时，不许悄悄套用永续参数。
        raise ValidationError(f"标的类别 {inst_type!r} 没有下单参数映射")
    return body


def _spot_order_params(intent: OrderIntent) -> dict[str, str]:
    """现货的参数集：只有现金模式，没有持仓方向也没有「只减仓」。"""

    if intent.pos_side or intent.reduce_only:
        raise ValidationError("现货下单没有 pos_side / reduce_only, 这两个参数只属于永续")
    return {"tdMode": SPOT_TD_MODE}


def _swap_order_params(intent: OrderIntent) -> dict[str, str]:
    """永续的参数集：保证金模式、持仓方向、「只减仓」都由这里给出。"""

    params = {"tdMode": SWAP_TD_MODE, "posSide": intent.pos_side or DEFAULT_POS_SIDE}
    if intent.reduce_only:
        params["reduceOnly"] = "true"
    return params


def _require_same_intent(
    intent: OrderIntent,
    *,
    inst_id: str,
    side: str,
    order_type: str,
    qty: Decimal,
    price: Decimal | None,
) -> None:
    """同一个幂等键只能对应同一个意图；不一致就报错，不拿旧订单冒充新订单。"""

    wanted = {
        "inst_id": intent.inst_id,
        "side": intent.side,
        "order_type": intent.order_type,
        "qty": intent.qty,
        "price": intent.price,
    }
    recorded = {
        "inst_id": inst_id,
        "side": side,
        "order_type": order_type,
        "qty": qty,
        "price": price,
    }
    differs = sorted(name for name in wanted if wanted[name] != recorded[name])
    if differs:
        raise ValidationError(
            f"client_order_id {intent.client_order_id} 已用于另一个订单意图,"
            f" 不一致的字段: {', '.join(differs)}"
        )


def _require_client_order_id(client_order_id: str) -> None:
    """幂等键的形状由上游决定：不符合就在本地拒绝，不拿一个注定 51000 的请求试。"""

    if _CLIENT_ORDER_ID.fullmatch(client_order_id) is None:
        raise ValidationError(f"client_order_id 必须是 1..32 位字母数字, 实际 {client_order_id!r}")


def _details(rows: list[Any]) -> list[dict[str, Any]]:
    """`/account/balance` 的应答把币种明细放在 `data[0].details` 里。"""

    if not rows:
        raise ExchangeError("余额应答为空")
    first = rows[0]
    if not isinstance(first, dict):
        raise ExchangeError("余额应答结构异常")
    details = first.get("details")
    if not isinstance(details, list):
        raise ExchangeError("余额应答缺少币种明细")
    return [row for row in details if isinstance(row, dict)]


def _currency_detail(rows: list[Any], currency: str) -> dict[str, Any]:
    """取指定币种的明细；没有该币种时退回第一条，仍没有就是空映射。"""

    details = _details(rows)
    for row in details:
        if str(row.get("ccy") or "") == currency:
            return row
    return details[0] if details else {}


def _margin_usage_ratio(
    used_margin: Decimal,
    available_margin: Decimal,
    fallback: Decimal | None,
) -> Decimal:
    """保证金使用率：0 到 1。上游没有足够字段时用 `mgnRatio` 兜底。"""

    denominator = used_margin + available_margin
    if denominator > 0:
        return used_margin / denominator
    if fallback is not None and Decimal(0) <= fallback <= Decimal(1):
        return fallback
    return Decimal(0)


def _products_by_category(
    instruments: Iterable[Instrument],
) -> dict[str, dict[str, tuple[str, str]]]:
    """「没有持仓接口的类别 → 币种 → (instId, 报价币种)」，只从标的表取。

    持仓接口不下发币种，余额只下发币种：两者的对应关系属于标的模块（`spot_currency`），
    适配层不拼 `instId` 字符串。三条取舍：

    - 只认本项目交易的报价币种（`DEFAULT_QUOTE_CURRENCY`）：OKX 上同一币种还挂着
      `BTC-AED`、`ETH-BTC` 这类报价，按符号排序取「最靠前的一档」会把 BTC 记到 AED
      报价的标的上，推导出一条账户里根本不存在的持仓。范围外的报价不推导，也不报错。
    - 报价币种自身是现金，不是持仓：只认 USDT 报价之后，`USDT` 余额不会成为任何标的的
      多头（它没有对应的 USDT 报价标的）。
    - 按类别分组：同一份余额被多个类别各推导一遍会让持仓凭空翻倍。
    """

    grouped: dict[str, dict[str, tuple[str, str]]] = {}
    for row in sorted(instruments, key=lambda item: item.symbol):
        if trading_rules(row.inst_type).has_position_endpoint:
            continue
        if row.quote_currency != DEFAULT_QUOTE_CURRENCY:
            continue
        grouped.setdefault(row.inst_type, {}).setdefault(
            spot_currency(row), (row.symbol, row.quote_currency)
        )
    return grouped


def _signed_qty(row: dict[str, Any]) -> Decimal:
    """上游持仓量按 `posSide` 定符号：多为正、空为负，`net` 本身带符号。"""

    qty = _decimal(row.get("pos") or "0")
    if str(row.get("posSide") or "") == "short":
        return -abs(qty)
    if str(row.get("posSide") or "") == "long":
        return abs(qty)
    return qty


def _parse_order(row: dict[str, Any]) -> Order:
    try:
        return Order(
            order_id=str(row["ordId"]),
            client_order_id=str(row.get("clOrdId") or ""),
            inst_id=str(row["instId"]),
            side=str(row["side"]),
            order_type=str(row["ordType"]),
            qty=_decimal(row.get("sz") or "0"),
            price=_decimal_or_none(row.get("px")),
            filled_qty=_decimal(row.get("accFillSz") or "0"),
            status=str(row.get("state") or ""),
            ts=utc_from_millis(row["cTime"]),
        )
    except KeyError as exc:
        raise ExchangeError(f"订单应答缺少字段:{exc}") from exc
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ExchangeError(f"订单应答数据非法:{row!r}") from exc


def _parse_fill(row: Any) -> Fill:
    if not isinstance(row, dict):
        raise ExchangeError("成交应答结构异常")
    try:
        return Fill(
            fill_id=str(row["tradeId"]),
            order_id=str(row["ordId"]),
            inst_id=str(row["instId"]),
            side=str(row["side"]),
            qty=_decimal(row.get("fillSz") or "0"),
            price=_decimal(row.get("fillPx") or "0"),
            fee=Money(_decimal(row.get("fee") or "0"), str(row.get("feeCcy") or SETTLE_CURRENCY)),
            ts=utc_from_millis(row["ts"]),
        )
    except KeyError as exc:
        raise ExchangeError(f"成交应答缺少字段:{exc}") from exc
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ExchangeError(f"成交应答数据非法:{row!r}") from exc


def _require_order_accepted(rows: list[Any], *, action: str) -> None:
    """单张订单类接口的逐单结果：`sCode` 非 0 就是上游拒绝了这次操作。"""

    row = _first_row(rows, action=action)
    s_code = str(row.get("sCode") or "0")
    if s_code != "0":
        raise ExecutionRejected(f"{action}被拒 {s_code}:{row.get('sMsg') or '未给出原因'}")


def _first_row(rows: list[Any], *, action: str) -> dict[str, Any]:
    if not rows:
        raise ExchangeError(f"{action}应答为空")
    row = rows[0]
    if not isinstance(row, dict):
        raise ExchangeError(f"{action}应答结构异常")
    return row


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ExchangeError(f"上游数值非法:{value!r}") from exc


def _decimal_or_none(value: Any) -> Decimal | None:
    """上游对市价单的 `px` 给空串：空就是「没有价格」，不是 0。"""

    if value is None or str(value).strip() == "":
        return None
    return _decimal(value)


def _decimal_or_zero(*values: Any) -> Decimal:
    """取第一个有值的十进制字段；都没有就是 0（上游确实没给，但账目字段不能空）。"""

    for value in values:
        parsed = _decimal_or_none(value)
        if parsed is not None:
            return parsed
    return Decimal(0)

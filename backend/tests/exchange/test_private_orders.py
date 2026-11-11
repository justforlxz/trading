"""私有下单：参数按类别分叉、`clientOrderId` 幂等、拒单与限流。

判据取自 MKACG-729 的验收：

- 现货与永续的下单参数各差一个都不行（现货不许出现 `posSide` / `reduceOnly`，
  永续必须带 `tdMode` 与 `posSide`）——假 server 按真实上游口径校验，参数形态错了
  就是 `51000`。
- 同一个 `clientOrderId` 提交 3 次，上游只有 1 张单；并且第一次提交之前登记已经
  落库（断电重发不会产生第二单）。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.config import Settings
from app.core import ExecutionRejected, OrderIntent, ValidationError
from app.db import session_scope
from app.exchange import ExchangeError, OkxPrivateClient, RateLimitedError, create_trade_port
from app.exchange.okx.ledger import (
    STATUS_RECORDED,
    STATUS_REJECTED,
    STATUS_SUBMITTED,
    OrderSubmission,
    claim_submission,
    load_submission,
)
from tests.exchange.conftest import FROZEN_NOW, SPOT_INST_ID, SWAP_INST_ID
from tests.fakes.okx.server import FakeOkxServer


def _limit(inst_id: str, *, price: str = "100", qty: str = "1", **kwargs: object) -> OrderIntent:
    return OrderIntent(
        inst_id=inst_id,
        side="buy",
        qty=Decimal(qty),
        order_type="limit",
        price=Decimal(price),
        **kwargs,  # type: ignore[arg-type]
    )


def _bodies(server: FakeOkxServer) -> list[str]:
    """假 OKX 收到的下单请求体（JSON 字符串，按到达顺序）。"""

    return [
        body
        for _method, path, _query, body in server.store.book.requests
        if path == "/api/v5/trade/order" and body
    ]


# ------------------------------------------------------------ 参数按类别分叉（各一处）


def test_spot_order_carries_cash_mode_and_no_swap_only_params(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """现货：`tdMode=cash`，请求里根本不存在 `posSide` / `reduceOnly` / `lever`。"""

    fake_okx_server.store.book.set_balance("USDT", available="10000")

    order = trade.place(_limit(SPOT_INST_ID, client_order_id="spot1"))

    assert order.client_order_id == "spot1"
    assert order.status == "live"
    body = _bodies(fake_okx_server)[0]
    assert '"tdMode":"cash"' in body
    for absent in ("posSide", "reduceOnly", "lever", "mgnMode"):
        assert absent not in body, f"现货下单不该出现 {absent}"


def test_swap_order_carries_margin_mode_and_position_side(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """永续：`tdMode=cross`、`posSide` 与 `reduceOnly` 由意图给出。"""

    order = trade.place(
        _limit(SWAP_INST_ID, client_order_id="swap1", pos_side="long", reduce_only=True)
    )

    assert order.inst_id == SWAP_INST_ID
    body = _bodies(fake_okx_server)[0]
    assert '"tdMode":"cross"' in body
    assert '"posSide":"long"' in body
    assert '"reduceOnly":"true"' in body


def test_swap_order_defaults_to_the_net_position_side(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """永续意图没给方向时按单向持仓模式发 `net`，而不是把这个参数省掉。"""

    trade.place(_limit(SWAP_INST_ID, client_order_id="swap2"))

    assert '"posSide":"net"' in _bodies(fake_okx_server)[0]


@pytest.mark.parametrize(
    ("reason", "kwargs"),
    [
        ("持仓方向只属于永续", {"pos_side": "long"}),
        ("只减仓只属于永续", {"reduce_only": True}),
    ],
)
def test_spot_order_rejects_swap_only_intents_before_any_request(
    trade: OkxPrivateClient,
    fake_okx_server: FakeOkxServer,
    reason: str,
    kwargs: dict[str, object],
) -> None:
    """现货意图带上永续参数时在本地就拒绝，一个请求都不发。"""

    with pytest.raises(ValidationError):
        trade.place(_limit(SPOT_INST_ID, client_order_id="spotbad", **kwargs))

    assert fake_okx_server.store.book.requests == [], f"{reason}: 不该有请求发出去"


def test_unknown_instrument_is_rejected_before_any_request(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """标的表里没有的 `instId` 直接拒绝，不发请求也不猜类别。"""

    with pytest.raises(ValidationError):
        trade.place(_limit("NOPE-USDT", client_order_id="ghost"))

    assert fake_okx_server.store.book.requests == []


def test_client_order_id_must_be_alphanumeric_before_any_request(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """上游不接受连字符（实测回 `51000 Parameter clOrdId error`），本地先拦下。"""

    with pytest.raises(ValidationError):
        trade.place(_limit(SPOT_INST_ID, client_order_id="idem-1"))

    assert fake_okx_server.store.book.requests == []


def test_missing_credentials_are_rejected_at_construction(
    private_settings: Settings,
) -> None:
    """凭据缺失在构造阶段就报错，而不是发一次注定 401 的请求。"""

    broken = private_settings.model_copy(update={"okx_secret_key": ""})

    with pytest.raises(ValidationError):
        create_trade_port(settings=broken)


# ------------------------------------------------------------------------ 幂等


def test_three_submissions_of_one_client_order_id_produce_one_upstream_order(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """同一 `clientOrderId` 提交 3 次：上游订单数 1，三次返回同一张单。"""

    fake_okx_server.store.book.set_balance("USDT", available="10000")
    intent = _limit(SPOT_INST_ID, client_order_id="idem1")

    orders = [trade.place(intent) for _ in range(3)]

    assert fake_okx_server.store.book.order_count == 1
    assert {order.order_id for order in orders} == {orders[0].order_id}
    assert len(_bodies(fake_okx_server)) == 1, "后两次不该再发下单请求"


def test_the_first_claim_wins_and_the_second_loses(trade_schema: None) -> None:
    """登记靠主键冲突判重：第一次 `True`、第二次 `False`。

    用 `rowcount` 判「插进去了没有」会恒为假（`ON CONFLICT DO NOTHING` 经 SQLAlchemy
    执行后是 `-1`），于是首次也被当成已存在，白多打一次上游查单。
    """

    intent = _limit(SPOT_INST_ID, client_order_id="claim1")

    assert claim_submission(intent, now=FROZEN_NOW) is True
    assert claim_submission(intent, now=FROZEN_NOW) is False


def test_a_first_submission_goes_straight_to_the_order_endpoint(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """首次提交不先查上游：登记拿到锁就直接下单，请求序列是 POST 加回读的 GET。"""

    fake_okx_server.store.book.set_balance("USDT", available="10000")

    trade.place(_limit(SPOT_INST_ID, client_order_id="first1"))

    calls = [(method, path) for method, path, _query, _body in fake_okx_server.store.book.requests]
    assert calls == [("POST", "/api/v5/trade/order"), ("GET", "/api/v5/trade/order")]


def test_the_claim_is_persisted_before_the_order_reaches_the_upstream(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """上游收到下单请求的那一刻，本地登记已经提交（另起会话能读到）。"""

    fake_okx_server.store.book.set_balance("USDT", available="10000")
    seen: list[str | None] = []

    def observe(_body: dict[str, object]) -> None:
        record = load_submission("persist1")
        seen.append(None if record is None else record.status)

    fake_okx_server.store.book.on_before_order = observe

    trade.place(_limit(SPOT_INST_ID, client_order_id="persist1"))

    assert seen == [STATUS_RECORDED]
    assert load_submission("persist1").status == STATUS_SUBMITTED  # type: ignore[union-attr]


def test_resend_after_a_failed_submission_does_not_duplicate_the_order(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """第一次没送进上游（上游 5xx，登记已落库），重发前先查上游：没有才重发，最终仍只有 1 张单。"""

    fake_okx_server.store.book.set_balance("USDT", available="10000")
    book = fake_okx_server.store.book
    intent = _limit(SPOT_INST_ID, client_order_id="crash1")

    fake_okx_server.scenarios.activate("upstream_error")
    with pytest.raises(ExchangeError):
        trade.place(intent)
    fake_okx_server.scenarios.reset()

    assert book.order_count == 0
    assert load_submission("crash1").status == STATUS_RECORDED  # type: ignore[union-attr]

    order = trade.place(intent)

    assert book.order_count == 1
    assert load_submission("crash1").status == STATUS_SUBMITTED  # type: ignore[union-attr]
    assert order.order_id == load_submission("crash1").order_id  # type: ignore[union-attr]


def test_an_order_created_upstream_without_a_local_claim_is_adopted_not_duplicated(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """本地登记丢了但上游有这张单：抓重复键回码，改用查单结果，不再下一张。"""

    fake_okx_server.store.book.set_balance("USDT", available="10000")
    intent = _limit(SPOT_INST_ID, client_order_id="lostledger")
    first = trade.place(intent)

    with session_scope() as session:
        session.delete(session.get(OrderSubmission, "lostledger"))

    again = trade.place(intent)

    assert again.order_id == first.order_id
    assert fake_okx_server.store.book.order_count == 1


def test_the_same_client_order_id_cannot_be_reused_for_a_different_intent(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """同一个幂等键换了数量再提交：报错，不拿旧订单冒充新订单。"""

    fake_okx_server.store.book.set_balance("USDT", available="10000")
    first = trade.place(_limit(SPOT_INST_ID, qty="1", client_order_id="reuse1"))

    with pytest.raises(ValidationError):
        trade.place(_limit(SPOT_INST_ID, qty="2", client_order_id="reuse1"))

    assert fake_okx_server.store.book.order_count == 1
    assert load_submission("reuse1").order_id == first.order_id  # type: ignore[union-attr]


def test_a_rejected_order_releases_its_client_order_id(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """拒单（余额不足）不留下「已提交」的假象；补足余额后同一个键还能下单。"""

    book = fake_okx_server.store.book
    book.set_balance("USDT", available="10")
    intent = _limit(SPOT_INST_ID, price="100", qty="1", client_order_id="retry1")

    with pytest.raises(ExecutionRejected):
        trade.place(intent)

    assert book.order_count == 0
    assert load_submission("retry1").status == STATUS_REJECTED  # type: ignore[union-attr]

    book.set_balance("USDT", available="10000")
    order = trade.place(intent)

    assert order.status == "live"
    assert book.order_count == 1


# ---------------------------------------------------------------- 上游故障与查单


def test_rate_limited_upstream_raises_rate_limited_error(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    fake_okx_server.scenarios.activate("rate_limited")

    with pytest.raises(RateLimitedError):
        trade.balance("USDT")


def test_a_wrong_secret_is_rejected_by_the_upstream(
    private_settings: Settings, frozen_clock, instruments: None
) -> None:
    """签名不对上游回 401：本地不吞掉，作为上游错误抛出。"""

    settings = private_settings.model_copy(update={"okx_secret_key": "wrong-secret"})
    client = create_trade_port(settings=settings, clock=frozen_clock)
    try:
        with pytest.raises(ExchangeError) as caught:
            client.balance("USDT")
    finally:
        client.close()

    assert "401" in str(caught.value)
    # 上游对鉴权失败用 HTTP 401 + 业务码 50113，两者都要保留下来。
    assert caught.value.code == "50113"


def test_cancel_moves_the_order_to_canceled(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    fake_okx_server.store.book.set_balance("USDT", available="10000")
    order = trade.place(_limit(SPOT_INST_ID, client_order_id="cancel1"))

    trade.cancel(SPOT_INST_ID, order.order_id)

    assert trade.order(SPOT_INST_ID, order.order_id).status == "canceled"


def test_cancel_of_an_unknown_order_is_rejected(trade: OkxPrivateClient) -> None:
    with pytest.raises(ExecutionRejected):
        trade.cancel(SPOT_INST_ID, "ord-does-not-exist")


def test_order_query_of_an_unknown_order_is_an_upstream_error(
    trade: OkxPrivateClient,
) -> None:
    with pytest.raises(ExchangeError):
        trade.order(SPOT_INST_ID, "ord-does-not-exist")


def test_fills_carry_the_fee_in_its_own_currency(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    """市价单成交后能查到成交记录；手续费是 `Money`，币种来自上游 `feeCcy`。"""

    book = fake_okx_server.store.book
    book.set_balance("USDT", available="10000")
    book.set_mark_price(SPOT_INST_ID, "100")

    order = trade.place(
        OrderIntent(
            inst_id=SPOT_INST_ID,
            side="buy",
            qty=Decimal("2"),
            order_type="market",
            client_order_id="market1",
        )
    )
    fills = trade.fills(SPOT_INST_ID, order.order_id)

    assert order.status == "filled"
    assert order.filled_qty == Decimal("2")
    assert len(fills) == 1
    assert fills[0].price == Decimal("100")
    assert fills[0].fee.amount == Decimal("0")
    assert fills[0].fee.currency == "USDT"


def test_fills_without_an_order_id_cover_the_whole_instrument(
    trade: OkxPrivateClient, fake_okx_server: FakeOkxServer
) -> None:
    book = fake_okx_server.store.book
    book.set_balance("USDT", available="10000")
    book.set_mark_price(SPOT_INST_ID, "100")
    trade.place(
        OrderIntent(
            inst_id=SPOT_INST_ID,
            side="buy",
            qty=Decimal("1"),
            order_type="market",
            client_order_id="market2",
        )
    )

    assert len(trade.fills(SPOT_INST_ID)) == 1
    assert trade.fills(SWAP_INST_ID) == []

"""paper 撮合：真实行情 + 手续费 + 滑点，与真实下单共用同一个订单对象。

判据来源（MKACG-730）：

- 给定行情、手续费率与滑点，成交价与费用与手算值相差小于 1e-9。
- paper 与真实下单走同一个订单对象，只是撮合来源不同。
- 同一个 `clientOrderId` 重放：不产生第二张单、不改持仓。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core import OrderIntent, ValidationError
from app.execution import (
    NET_POS_SIDE,
    SIDE_LONG,
    SIDE_SHORT,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_FILLED,
    STATUS_OPEN,
    Order,
    PaperBroker,
    PaperRejected,
    accept,
    apply_fill,
    new_order,
)
from app.instrument import Instrument
from tests.execution.conftest import (
    FROZEN_NOW,
    QUOTE_CURRENCY,
    SPOT_INST_ID,
    SWAP_INST_ID,
    make_fill,
    make_intent,
)

FEE_RATE = Decimal("0.0005")
SLIPPAGE = Decimal("0.001")
TOLERANCE = Decimal("1e-9")
NOW = FROZEN_NOW
MARKET_PRICE = Decimal("100")


def _broker(*, fee_rate: Decimal = FEE_RATE, slippage: Decimal = SLIPPAGE) -> PaperBroker:
    return PaperBroker(fee_rate=fee_rate, slippage=slippage)


# ------------------------------------------------------------------ 成交价与手续费


def test_market_buy_fills_at_the_slipped_price_with_a_hand_computed_fee(
    spot_instrument: Instrument,
) -> None:
    """手算：100 × (1 + 0.001) = 100.1；费用 100.1 × 2 × 0.0005 = 0.1001。"""

    broker = _broker()
    order = broker.place(make_intent(qty="2"), spot_instrument, market_price=MARKET_PRICE, now=NOW)

    (fill,) = broker.fills(order.client_order_id)
    expected_price = Decimal("100.1")
    expected_fee = Decimal("0.1001")
    assert abs(fill.price - expected_price) < TOLERANCE
    assert abs(fill.fee.amount - expected_fee) < TOLERANCE
    assert fill.fee.currency == QUOTE_CURRENCY
    assert fill.qty == Decimal("2")
    assert order.status == STATUS_FILLED
    assert order.avg_fill_price == expected_price


def test_market_sell_fills_below_the_market_price(spot_instrument: Instrument) -> None:
    """手算：100 × (1 - 0.001) = 99.9；费用 99.9 × 1 × 0.0005 = 0.04995。"""

    broker = _broker()
    broker.place(make_intent(qty="2"), spot_instrument, market_price=MARKET_PRICE, now=NOW)
    order = broker.place(
        make_intent(client_order_id="cli2", side="sell", qty="1"),
        spot_instrument,
        market_price=MARKET_PRICE,
        now=NOW,
    )

    (fill,) = broker.fills(order.client_order_id)
    expected_price = Decimal("99.9")
    expected_fee = Decimal("0.04995")
    assert abs(fill.price - expected_price) < TOLERANCE
    assert abs(fill.fee.amount - expected_fee) < TOLERANCE


def test_limit_buy_below_the_slipped_price_rests_without_filling(
    spot_instrument: Instrument,
) -> None:
    """限价 99 低于滑点后的 100.1：订单停在 `open`，等撤单，不成交。"""

    broker = _broker()
    order = broker.place(
        make_intent(order_type="limit", price="99"),
        spot_instrument,
        market_price=MARKET_PRICE,
        now=NOW,
    )

    assert order.status == STATUS_OPEN
    assert broker.fills(order.client_order_id) == ()
    assert broker.positions() == ()


def test_limit_buy_at_or_above_the_slipped_price_fills_at_the_market_price(
    spot_instrument: Instrument,
) -> None:
    """限价 101 高于滑点后的 100.1：以 100.1 成交，不拿限价当成交价。"""

    broker = _broker()
    order = broker.place(
        make_intent(order_type="limit", price="101"),
        spot_instrument,
        market_price=MARKET_PRICE,
        now=NOW,
    )

    (fill,) = broker.fills(order.client_order_id)
    assert order.status == STATUS_FILLED
    assert abs(fill.price - Decimal("100.1")) < TOLERANCE


def test_swap_position_created_by_paper_keeps_the_unknown_swap_columns(
    swap_instrument: Instrument,
) -> None:
    """模拟账户不模拟保证金与强平：永续持仓的杠杆/保证金/强平价保持 `None`（未知）。

    持仓方向仍然要记：单向模式下是 `net`，这是永续才有的字段，现货上必须是 `None`。
    """

    broker = _broker()
    order = broker.place(
        make_intent(client_order_id="cli-swap", inst_id=SWAP_INST_ID),
        swap_instrument,
        market_price=MARKET_PRICE,
        now=NOW,
    )

    (fill,) = broker.fills(order.client_order_id)
    assert fill.fee.currency == QUOTE_CURRENCY
    (position,) = broker.positions()
    assert position.pos_side == NET_POS_SIDE
    assert (position.leverage, position.margin, position.liq_price) == (None, None, None)


# ---------------------------------------------------------------------- 幂等


def test_replaying_the_same_client_order_id_creates_no_second_order_and_keeps_positions(
    spot_instrument: Instrument,
) -> None:
    """同一幂等键重放：订单只有一张、成交只有一笔、持仓一个字段都不变。"""

    broker = _broker()
    intent = make_intent(qty="2")
    first = broker.place(intent, spot_instrument, market_price=MARKET_PRICE, now=NOW)
    positions_before = broker.positions()

    replay = broker.place(intent, spot_instrument, market_price=Decimal("120"), now=NOW)

    assert replay == first
    assert len(broker.orders()) == 1
    assert len(broker.fills(intent.client_order_id)) == 1
    assert broker.positions() == positions_before


def test_replaying_with_a_different_intent_is_rejected(spot_instrument: Instrument) -> None:
    """同一个键配另一份意图是调用方拿错了键：报错，不拿旧订单冒充新订单。"""

    broker = _broker()
    broker.place(make_intent(qty="2"), spot_instrument, market_price=MARKET_PRICE, now=NOW)

    with pytest.raises(ValidationError):
        broker.place(make_intent(qty="3"), spot_instrument, market_price=MARKET_PRICE, now=NOW)


def test_paper_requires_a_client_order_id(spot_instrument: Instrument) -> None:
    """paper 订单以幂等键为身份，缺了就无法重放判重。"""

    intent = OrderIntent(
        inst_id=SPOT_INST_ID,
        side="buy",
        qty=Decimal("1"),
        order_type="market",
    )

    with pytest.raises(ValidationError):
        _broker().place(intent, spot_instrument, market_price=MARKET_PRICE, now=NOW)


# ------------------------------------------------- 与真实下单共用同一个订单对象


def test_paper_and_venue_paths_produce_the_same_order_object(
    spot_instrument: Instrument,
) -> None:
    """paper 撮合与交易所成交都产出 `Order`：区别只在成交来源，不是两套订单类型。"""

    intent = make_intent(qty="2")
    paper_order = _broker().place(intent, spot_instrument, market_price=MARKET_PRICE, now=NOW)

    venue_order = accept(new_order(intent, now=NOW), "ord-from-venue", now=NOW)
    venue_order = apply_fill(
        venue_order,
        make_fill(order_id="ord-from-venue", qty="2", price="100.1", fee="0.1001"),
        now=NOW,
    )

    assert type(paper_order) is Order
    assert type(venue_order) is type(paper_order)
    assert paper_order.status == venue_order.status
    assert paper_order.filled_qty == venue_order.filled_qty
    assert paper_order.avg_fill_price == venue_order.avg_fill_price


# ---------------------------------------------------------------- 拒单与撤单


def test_broker_rejects_a_sell_without_a_position(spot_instrument: Instrument) -> None:
    """模拟账户没有可减持仓：订单落 `failed`，持仓仍为空。"""

    broker = _broker()
    intent = make_intent(client_order_id="cli2", side="sell", qty="1")

    with pytest.raises(PaperRejected):
        broker.place(intent, spot_instrument, market_price=MARKET_PRICE, now=NOW)

    assert broker.order(intent.client_order_id).status == STATUS_FAILED
    assert broker.positions() == ()


def test_a_rejected_order_is_recorded_as_failed_and_can_be_retried(
    spot_instrument: Instrument,
) -> None:
    """参数被账本拒绝时订单落 `failed`（不是永远 `open`），同一个键改正参数后能重试。"""

    broker = _broker()
    rejected_intent = make_intent(client_order_id="cli-fix", reduce_only=True)

    with pytest.raises(ValidationError):
        broker.place(rejected_intent, spot_instrument, market_price=MARKET_PRICE, now=NOW)

    rejected = broker.order("cli-fix")
    assert rejected is not None
    assert (rejected.status, rejected.filled_qty) == (STATUS_FAILED, Decimal("0"))
    assert broker.fills("cli-fix") == ()
    assert broker.positions() == ()

    retried = broker.place(
        make_intent(client_order_id="cli-fix"),
        spot_instrument,
        market_price=MARKET_PRICE,
        now=NOW,
    )

    assert retried.status == STATUS_FILLED
    assert len(broker.fills("cli-fix")) == 1
    assert len(broker.orders()) == 1


def test_replay_detects_a_changed_position_side_or_reduce_only(
    swap_instrument: Instrument,
) -> None:
    """只改 `pos_side` 或 `reduce_only` 也是另一个意图：不能当重放返回旧订单。

    否则「先开仓、再用同一个键提交平仓」会被静默丢弃，调用方却拿到一张已成交的开仓单。
    """

    broker = _broker()
    opened = broker.place(
        make_intent(client_order_id="cli-hedge", inst_id=SWAP_INST_ID, pos_side=SIDE_LONG),
        swap_instrument,
        market_price=MARKET_PRICE,
        now=NOW,
    )
    assert opened.status == STATUS_FILLED

    with pytest.raises(ValidationError):
        broker.place(
            make_intent(
                client_order_id="cli-hedge",
                inst_id=SWAP_INST_ID,
                pos_side=SIDE_LONG,
                reduce_only=True,
            ),
            swap_instrument,
            market_price=MARKET_PRICE,
            now=NOW,
        )
    with pytest.raises(ValidationError):
        broker.place(
            make_intent(client_order_id="cli-hedge", inst_id=SWAP_INST_ID, pos_side=SIDE_SHORT),
            swap_instrument,
            market_price=MARKET_PRICE,
            now=NOW,
        )


def test_cancel_turns_a_resting_limit_order_into_cancelled(
    spot_instrument: Instrument,
) -> None:
    broker = _broker()
    order = broker.place(
        make_intent(order_type="limit", price="99"),
        spot_instrument,
        market_price=MARKET_PRICE,
        now=NOW,
    )

    cancelled = broker.cancel(order.client_order_id, now=NOW)

    assert cancelled.status == STATUS_CANCELLED
    assert cancelled.filled_qty == Decimal("0")


def test_cancelling_a_filled_order_is_rejected(spot_instrument: Instrument) -> None:
    broker = _broker()
    order = broker.place(make_intent(qty="1"), spot_instrument, market_price=MARKET_PRICE, now=NOW)

    with pytest.raises(ValidationError):
        broker.cancel(order.client_order_id, now=NOW)


def test_cancelling_an_unknown_order_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _broker().cancel("nope", now=NOW)


# ---------------------------------------------------------------------- 参数校验


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fee_rate": Decimal("-0.0005")},
        {"fee_rate": Decimal("1")},
        {"slippage": Decimal("-0.001")},
        {"slippage": Decimal("1")},
        {"fee_rate": 0.0005},
    ],
    ids=["费率为负", "费率等于 1", "滑点为负", "滑点等于 1", "费率不是 Decimal"],
)
def test_rates_must_be_decimals_between_zero_and_one(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PaperBroker(**{**{"fee_rate": FEE_RATE, "slippage": SLIPPAGE}, **kwargs})


def test_a_non_positive_market_price_is_rejected(spot_instrument: Instrument) -> None:
    with pytest.raises(ValidationError):
        _broker().place(make_intent(), spot_instrument, market_price=Decimal("0"), now=NOW)


def test_the_instrument_must_match_the_intent(spot_instrument: Instrument) -> None:
    """意图与标的行必须指同一个标的：拿错了配对会记到别的产品上。"""

    with pytest.raises(ValidationError):
        _broker().place(
            make_intent(inst_id=SWAP_INST_ID, order_type="market"),
            spot_instrument,
            market_price=MARKET_PRICE,
            now=NOW,
        )

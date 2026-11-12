"""Manual 模式：计划生成、人工确认、幂等下单与失败不重发。

判据来源（MKACG-731）：

- 未确认不落单：paper 与假 OKX 两个后端各一条，订单数都为 0。
- 确认后只下一单：同一计划确认一次后 paper 订单数为 1；同一 `clientOrderId`
  再确认一次仍为 1。
- `clientOrderId` 由计划派生，形状满足真实适配器的 `^[0-9A-Za-z]{1,32}$`。
- 拒单与超时各一条：本地 `failed`、重试计数 0、上游订单数不增加。
- 确认绑定计划内容：沿用同一 `plan_id` 与 `version` 但数量变化时，旧确认失效。
- 多腿计划中途抛异常：已经下出的前序腿必须留在本地状态里。
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

import pytest

from app.config import Settings
from app.core import (
    Conflict,
    InstrumentRef,
    OrderIntent,
    ReplayClock,
    Signal,
    ValidationError,
)
from app.db import init_db
from app.exchange import create_trade_port
from app.execution import (
    STATUS_FAILED,
    ConfirmationRecord,
    ExecutionService,
    Order,
    OrderBackend,
    PaperBroker,
    PaperOrderBackend,
    Placement,
    PlacementResult,
    PlanLeg,
    TradePlan,
    TradePortBackend,
    build_plan,
    client_order_id,
    new_order,
    paper_snapshot,
    plan_digest,
    require_confirmation,
)
from app.instrument import Instrument, sync_instruments
from app.strategy import TargetLeg, TargetPortfolio
from tests.execution.conftest import (
    FROZEN_NOW,
    PRODUCT_KEY,
    SPOT_INST_ID,
    SWAP_INST_ID,
)
from tests.fakes.okx.server import FakeOkxServer

#: 真实适配器对 `clOrdId` 的要求；测试自己声明契约，不从生产模块取常量。
CLIENT_ORDER_ID_PATTERN = re.compile(r"[0-9A-Za-z]{1,32}")

CAPITAL = Decimal("1000")
PRICE = Decimal("100")
WEIGHT = Decimal("0.5")
FEE_RATE = Decimal("0.0005")
SLIPPAGE = Decimal("0.001")


def _target(*, side: str = "long") -> TargetPortfolio:
    return TargetPortfolio(
        as_of=FROZEN_NOW,
        legs=(TargetLeg(product_key=PRODUCT_KEY, side=side, target_weight=WEIGHT),),
    )


def _signal(*, inst_id: str = SPOT_INST_ID, side: str = "long") -> Signal:
    return Signal(inst_id=inst_id, side=side, strength=0.8, ts=FROZEN_NOW)


def _ref(instrument: Instrument) -> InstrumentRef:
    """把标的行投影成策略层使用的 `InstrumentRef`，只带数量换算需要的字段。"""

    return InstrumentRef(
        inst_id=instrument.symbol,
        inst_type=instrument.inst_type,
        base_ccy=instrument.base_currency,
        quote_ccy=instrument.quote_currency,
        state=instrument.trading_status,
        tick_size=instrument.tick_size,
        lot_size=instrument.lot_size,
        min_size=instrument.min_order_size,
        ct_val_ccy=instrument.product_key,
        settle_ccy=instrument.settle_ccy or "",
        ct_val=instrument.ct_val,
        ct_mult=instrument.ct_mult,
        max_lever=instrument.max_lever,
    )


def _plan(
    *,
    instruments: dict[str, InstrumentRef],
    signal: Signal | None = None,
    prices: dict[str, Decimal] | None = None,
    price_caps: dict[str, Decimal] | None = None,
    side: str = "long",
    version: int = 1,
):
    return build_plan(
        plan_id="plan-1",
        version=version,
        strategy_id="si-1",
        target=_target(side=side),
        signals=(signal or _signal(side=side),),
        instruments=instruments,
        prices=prices or {SPOT_INST_ID: PRICE},
        capital=CAPITAL,
        price_caps=price_caps,
    )


def _paper_service(spot_instrument: Instrument) -> tuple[ExecutionService, PaperBroker]:
    broker = PaperBroker(fee_rate=FEE_RATE, slippage=SLIPPAGE)
    backend: OrderBackend = PaperOrderBackend(
        broker,
        instruments={SPOT_INST_ID: spot_instrument},
        prices={SPOT_INST_ID: PRICE},
    )
    return ExecutionService(backend, clock=ReplayClock(FROZEN_NOW)), broker


def _settings(server: FakeOkxServer, *, timeout: float = 10.0) -> Settings:
    credentials = server.store.book.credentials
    return Settings(
        okx_rest_base_url=server.base_url,
        okx_http_timeout_seconds=timeout,
        okx_http_max_retries=0,
        okx_rate_limit_capacity=1000,
        okx_rate_limit_refill_per_second=1000.0,
        okx_api_key=credentials.api_key,
        okx_secret_key=credentials.secret,
        okx_passphrase=credentials.passphrase,
        okx_demo=True,
    )


@pytest.fixture()
def live_instruments() -> None:
    """真实路径只认标的表：先把测试用的现货行按同一条落库路径写进去。"""

    init_db()
    sync_instruments(
        [
            InstrumentRef(
                inst_id=SPOT_INST_ID,
                inst_type="SPOT",
                base_ccy="XAAPL",
                quote_ccy="USDT",
                state="live",
                inst_category="3",
                tick_size=Decimal("0.01"),
                lot_size=Decimal("0.001"),
                min_size=Decimal("0.001"),
            )
        ]
    )


def _order_posts(server: FakeOkxServer) -> list[str]:
    return [
        body
        for method, path, _query, body in server.store.book.requests
        if method == "POST" and path == "/api/v5/trade/order"
    ]


# ------------------------------------------------------------------ 计划生成


def test_plan_carries_each_leg_and_a_derived_idempotency_key(
    spot_instrument: Instrument,
) -> None:
    """0.5 × 1000 / 100 = 5；价格上限 101 进入计划。"""

    plan = _plan(
        instruments={PRODUCT_KEY: _ref(spot_instrument)},
        price_caps={PRODUCT_KEY: Decimal("101")},
    )

    assert isinstance(plan, TradePlan)
    (leg,) = plan.legs
    assert isinstance(leg, PlanLeg)
    assert leg.product_key == PRODUCT_KEY
    assert leg.inst_id == SPOT_INST_ID
    assert leg.inst_type == "SPOT"
    assert leg.side == "buy"
    assert leg.qty == Decimal("5")
    assert leg.price_cap == Decimal("101")
    assert leg.strategy_id == "si-1"

    key = client_order_id(plan, leg)
    assert CLIENT_ORDER_ID_PATTERN.fullmatch(key) is not None
    assert len(key) == 32
    assert client_order_id(plan, leg) == key
    assert (
        client_order_id(
            _plan(
                instruments={PRODUCT_KEY: _ref(spot_instrument)},
                price_caps={PRODUCT_KEY: Decimal("101")},
                version=2,
            ),
            leg,
        )
        != key
    )


def test_swap_short_leg_sells_with_the_short_position_side(
    swap_instrument: Instrument,
) -> None:
    """0.5 × 1000 / (100 × 1) = 5 张；空头目标对应卖出。"""

    plan = _plan(
        instruments={PRODUCT_KEY: _ref(swap_instrument)},
        signal=_signal(inst_id=SWAP_INST_ID, side="short"),
        prices={SWAP_INST_ID: PRICE},
        side="short",
    )

    (leg,) = plan.legs
    assert leg.inst_id == SWAP_INST_ID
    assert leg.inst_type == "SWAP"
    assert leg.side == "sell"
    assert leg.qty == Decimal("5")


def test_signal_direction_must_match_the_target_leg(spot_instrument: Instrument) -> None:
    with pytest.raises(ValidationError, match="信号方向"):
        build_plan(
            plan_id="plan-1",
            version=1,
            strategy_id="si-1",
            target=_target(side="long"),
            signals=(_signal(side="short"),),
            instruments={PRODUCT_KEY: _ref(spot_instrument)},
            prices={SPOT_INST_ID: PRICE},
            capital=CAPITAL,
        )


# ------------------------------------------------------------------ 未确认不落单


def test_paper_places_no_order_before_confirmation(spot_instrument: Instrument) -> None:
    service, broker = _paper_service(spot_instrument)
    plan = _plan(instruments={PRODUCT_KEY: _ref(spot_instrument)})

    with pytest.raises(Conflict, match="未确认"):
        service.place(plan)

    assert broker.orders() == ()


def test_fake_okx_places_no_order_before_confirmation(
    fake_okx_server: FakeOkxServer,
) -> None:
    trade = create_trade_port(settings=_settings(fake_okx_server))
    try:
        service = ExecutionService(TradePortBackend(trade), clock=ReplayClock(FROZEN_NOW))
        plan = _plan(
            instruments={PRODUCT_KEY: _ref(_instrument_for_plan())},
            price_caps={PRODUCT_KEY: PRICE},
        )
        with pytest.raises(Conflict, match="未确认"):
            service.place(plan)
    finally:
        trade.close()

    assert fake_okx_server.store.book.order_count == 0
    assert _order_posts(fake_okx_server) == []


def _instrument_for_plan() -> Instrument:
    """未确认用例不会发请求，只需要一个形状正确的标的行。"""

    return Instrument(
        symbol=SPOT_INST_ID,
        inst_type="SPOT",
        product_key=PRODUCT_KEY,
        asset_type="tokenized_equity",
        exchange="okx",
        base_currency=PRODUCT_KEY,
        quote_currency="USDT",
        tick_size=Decimal("0.01"),
        lot_size=Decimal("0.001"),
        min_order_size=Decimal("0.001"),
        trading_status="live",
    )


# ------------------------------------------------------------------ 确认后只下一单


def test_confirmed_paper_plan_places_exactly_one_order_and_replay_is_idempotent(
    spot_instrument: Instrument,
) -> None:
    service, broker = _paper_service(spot_instrument)
    plan = _plan(instruments={PRODUCT_KEY: _ref(spot_instrument)})
    service.confirm(plan, confirmed_by="lxz")

    first = service.place(plan)
    service.confirm(plan, confirmed_by="lxz")
    second = service.place(plan)

    assert isinstance(first, PlacementResult)
    assert len(broker.orders()) == 1
    assert first.orders[0].client_order_id == second.orders[0].client_order_id
    assert second.placements[0].reused is True
    assert broker.order(first.orders[0].client_order_id) is not None


def test_confirmation_is_bound_to_the_plan_version(spot_instrument: Instrument) -> None:
    service, broker = _paper_service(spot_instrument)
    plan_v1 = _plan(instruments={PRODUCT_KEY: _ref(spot_instrument)})
    service.confirm(plan_v1, confirmed_by="lxz")
    plan_v2 = _plan(instruments={PRODUCT_KEY: _ref(spot_instrument)}, version=2)

    with pytest.raises(Conflict, match="未确认"):
        service.place(plan_v2)

    assert broker.orders() == ()

    stale = ConfirmationRecord(
        plan_id=plan_v1.plan_id,
        plan_version=plan_v1.version,
        plan_digest=plan_digest(plan_v1),
        confirmed_by="lxz",
        confirmed_at=FROZEN_NOW,
    )
    with pytest.raises(Conflict, match="版本"):
        require_confirmation(plan_v2, stale)


def test_confirmation_is_bound_to_the_plan_content(spot_instrument: Instrument) -> None:
    """同一 plan_id 与 version，价格变化让数量从 5 变成 10，旧确认必须失效。"""

    service, broker = _paper_service(spot_instrument)
    confirmed = _plan(instruments={PRODUCT_KEY: _ref(spot_instrument)})
    service.confirm(confirmed, confirmed_by="lxz")
    changed = build_plan(
        plan_id=confirmed.plan_id,
        version=confirmed.version,
        strategy_id="si-1",
        target=_target(),
        signals=(_signal(),),
        instruments={PRODUCT_KEY: _ref(spot_instrument)},
        prices={SPOT_INST_ID: Decimal("50")},
        capital=CAPITAL,
    )
    assert changed.legs[0].qty == Decimal("10")

    with pytest.raises(Conflict, match="内容"):
        service.place(changed)

    assert broker.orders() == ()


class _FailsOnSecondLeg:
    """第一腿正常返回订单，第二腿抛出非执行类异常的假后端。"""

    def __init__(self) -> None:
        self.calls: list[OrderIntent] = []

    def place(self, intent: OrderIntent, *, now: datetime) -> Order:
        self.calls.append(intent)
        if len(self.calls) > 1:
            raise ValidationError("第二腿的标的装配缺失")
        return new_order(intent, now=now)


def test_unexpected_error_keeps_the_orders_already_placed() -> None:
    backend = _FailsOnSecondLeg()
    service = ExecutionService(backend, clock=ReplayClock(FROZEN_NOW))
    plan = TradePlan(
        plan_id="plan-multi",
        version=1,
        as_of=FROZEN_NOW,
        legs=(
            PlanLeg(
                product_key=PRODUCT_KEY,
                inst_id=SPOT_INST_ID,
                inst_type="SPOT",
                side="buy",
                qty=Decimal("2"),
                strategy_id="si-1",
            ),
            PlanLeg(
                product_key=PRODUCT_KEY,
                inst_id=SWAP_INST_ID,
                inst_type="SWAP",
                side="buy",
                qty=Decimal("3"),
                strategy_id="si-1",
            ),
        ),
    )
    service.confirm(plan, confirmed_by="lxz")

    with pytest.raises(ValidationError, match="第二腿"):
        service.place(plan)

    assert [order.client_order_id for order in service.state.orders] == [
        client_order_id(plan, plan.legs[0])
    ]


# ------------------------------------------------------------------ 拒单与超时


def test_paper_snapshot_syncs_orders_fills_and_positions(
    spot_instrument: Instrument,
) -> None:
    """paper 账本本身就是事实来源：同步后本地订单、成交与持仓与账本一致。"""

    service, broker = _paper_service(spot_instrument)
    plan = _plan(instruments={PRODUCT_KEY: _ref(spot_instrument)})
    service.confirm(plan, confirmed_by="lxz")
    service.place(plan)

    result = service.sync(paper_snapshot(broker))

    (order,) = result.state.orders
    assert order.status == "filled"
    assert len(result.state.fills) == 1
    (position,) = result.state.positions
    assert position.qty == Decimal("5")


def test_rejection_marks_the_local_order_failed_without_resending(
    fake_okx_server: FakeOkxServer,
    live_instruments: None,
) -> None:
    """假 OKX 账户没有 USDT：现货买单按 51008 拒单，上游订单数保持 0。"""

    trade = create_trade_port(settings=_settings(fake_okx_server))
    try:
        service = ExecutionService(TradePortBackend(trade), clock=ReplayClock(FROZEN_NOW))
        plan = _plan(
            instruments={PRODUCT_KEY: _ref(_instrument_for_plan())},
            price_caps={PRODUCT_KEY: PRICE},
        )
        service.confirm(plan, confirmed_by="lxz")

        result = service.place(plan)
    finally:
        trade.close()

    (placement,) = result.placements
    assert isinstance(placement, Placement)
    assert placement.order.status == STATUS_FAILED
    assert placement.retry_count == 0
    assert placement.error is not None
    assert fake_okx_server.store.book.order_count == 0
    assert len(_order_posts(fake_okx_server)) == 1


def test_timeout_marks_the_local_order_failed_without_resending(
    fake_okx_server: FakeOkxServer,
    live_instruments: None,
) -> None:
    """上游慢于客户端超时：本地落 `failed`，不自动重发。"""

    fake_okx_server.scenarios.slow(0.5)
    trade = create_trade_port(settings=_settings(fake_okx_server, timeout=0.05))
    try:
        service = ExecutionService(TradePortBackend(trade), clock=ReplayClock(FROZEN_NOW))
        plan = _plan(
            instruments={PRODUCT_KEY: _ref(_instrument_for_plan())},
            price_caps={PRODUCT_KEY: PRICE},
        )
        service.confirm(plan, confirmed_by="lxz")

        result = service.place(plan)
    finally:
        trade.close()
        fake_okx_server.scenarios.reset()

    (placement,) = result.placements
    assert placement.order.status == STATUS_FAILED
    assert placement.retry_count == 0
    assert placement.error is not None
    assert fake_okx_server.store.book.order_count == 0

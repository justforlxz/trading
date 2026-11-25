"""持仓卡片：排序、止损三态、以及「没有行情也保留卡片」。

排序与占比都在后端算完，前端只画。没有行情的持仓必须照样出卡片：整卡消失的话，
用户会以为那条持仓已经平掉了。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core import AccountSnapshot, ExchangePosition, StopOrder
from app.exchange.okx.instruments import parse_instruments
from app.instrument import sync_instruments
from app.positions import account_summary, position_cards, record_exchange_snapshot
from tests.api.conftest import seed_daily
from tests.exchange.conftest import SWAP_INSTRUMENT

CAPTURED_AT = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def _snapshot(equity: str = "1000") -> AccountSnapshot:
    return AccountSnapshot(
        currency="USDT",
        equity=Decimal(equity),
        available_equity=Decimal("600"),
        cash_balance=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        used_margin=Decimal("0"),
        available_margin=Decimal("600"),
        margin_ratio=Decimal("0"),
    )


def _position(
    pos_id: str,
    *,
    inst_id: str = "AAPL-USDT-SWAP",
    pos_side: str = "long",
    size: str = "8",
    mark_px: str | None = "231.42",
    upl: str | None = "10",
    lever: str | None = "3",
) -> ExchangePosition:
    return ExchangePosition(
        pos_id=pos_id,
        inst_id=inst_id,
        pos_side=pos_side,
        size=Decimal(size),
        avg_px=Decimal("226.80"),
        mark_px=None if mark_px is None else Decimal(mark_px),
        upl=None if upl is None else Decimal(upl),
        upl_ratio=Decimal("0"),
        lever=None if lever in (None, "") else Decimal(lever),
        mgn_mode="isolated",
        liq_px=None,
        margin=Decimal("0"),
    )


def _write(positions: list[ExchangePosition], *, stops: list[StopOrder] | None = None) -> None:
    record_exchange_snapshot(
        captured_at=CAPTURED_AT,
        source="okx_rest",
        snapshot=_snapshot(),
        positions=positions,
        stops=stops if stops is not None else [],
        stops_available=stops is not None,
    )


def test_cards_are_sorted_by_absolute_unrealized_pnl(client: TestClient) -> None:
    sync_instruments(parse_instruments([SWAP_INSTRUMENT]))
    _write(
        [
            _position("pos-small", upl="5"),
            _position("pos-big-loss", upl="-30"),
            _position("pos-mid", upl="10"),
        ]
    )

    view = position_cards()

    assert [card.pos_id for card in view.items] == ["pos-big-loss", "pos-mid", "pos-small"]


def test_card_without_market_data_is_kept_with_null_numbers(client: TestClient) -> None:
    """没有行情时卡片仍在，价格与盈亏为空，由界面用骨架占位。"""

    sync_instruments(parse_instruments([SWAP_INSTRUMENT]))
    _write(
        [
            _position("pos-priced", upl="5"),
            _position(
                "pos-no-quote",
                inst_id="SPCX-USDT-SWAP",
                mark_px=None,
                upl=None,
            ),
        ]
    )

    cards = {card.pos_id: card for card in position_cards().items}

    assert set(cards) == {"pos-priced", "pos-no-quote"}
    pending = cards["pos-no-quote"]
    assert pending.mark_px is None
    assert pending.upl is None
    assert pending.notional is None
    assert pending.weight_pct is None


def test_stop_states_reach_the_cards(client: TestClient) -> None:
    sync_instruments(parse_instruments([SWAP_INSTRUMENT]))
    _write(
        [
            _position("pos-with-stop"),
            _position("pos-without-stop"),
        ],
        stops=[
            StopOrder(
                inst_id="AAPL-USDT-SWAP",
                order_id="algo-1",
                order_type="conditional",
                side="sell",
                stop_px=Decimal("220"),
                pos_side=None,
            )
        ],
    )

    # 两条持仓同标的、同向，止损价对两条都成立；用不同标的区分会引入第二个标的定义。
    card = position_cards().items[0]
    assert card.stop_status == "confirmed"
    assert card.stop_px == Decimal("220")
    # 标记价 231.42 → 止损 220，距离 4.935%
    assert float(card.stop_distance_pct) == pytest.approx(4.935, abs=1e-3)


def test_unavailable_stops_are_not_reported_as_missing(client: TestClient) -> None:
    """这次没问到止损：卡片必须显示「未取到」，不是「未挂」。"""

    sync_instruments(parse_instruments([SWAP_INSTRUMENT]))
    _write([_position("pos-1")])

    card = position_cards().items[0]

    assert card.stop_status == "unavailable"
    assert card.stop_px is None


def test_confirmed_no_stop_is_reported_as_none(client: TestClient) -> None:
    sync_instruments(parse_instruments([SWAP_INSTRUMENT]))
    _write([_position("pos-1")], stops=[])

    card = position_cards().items[0]

    assert card.stop_status == "none"


def test_weight_is_relative_to_the_known_gross(client: TestClient) -> None:
    sync_instruments(parse_instruments([SWAP_INSTRUMENT]))
    _write([_position("pos-1", size="8")])

    card = position_cards().items[0]

    assert card.notional == Decimal("1851.36")
    assert card.weight_pct == Decimal("100")


def test_push_without_stop_data_keeps_the_synced_stop_state(client: TestClient) -> None:
    """私有频道推送不携带止损：它既不能抹掉「确认无止损」，也不能抹掉「已设止损」。

    推送与 REST 同步会落在同一个 `(account_id, pos_id, captured_at)` 上，所以只要
    推送无条件写止损列，页面上就永远只剩「未取到」。
    """

    sync_instruments(parse_instruments([SWAP_INSTRUMENT]))
    _write([_position("pos-1")], stops=[])
    assert position_cards().items[0].stop_status == "none"

    record_exchange_snapshot(
        captured_at=CAPTURED_AT,
        source="okx_ws",
        positions=[_position("pos-1", upl="11")],
    )

    card = position_cards().items[0]
    assert card.stop_status == "none"
    assert card.upl == Decimal("11")


def test_push_without_stop_data_keeps_a_confirmed_stop_price(client: TestClient) -> None:
    sync_instruments(parse_instruments([SWAP_INSTRUMENT]))
    _write(
        [_position("pos-1")],
        stops=[
            StopOrder(
                inst_id="AAPL-USDT-SWAP",
                order_id="algo-1",
                order_type="conditional",
                side="sell",
                stop_px=Decimal("220"),
                pos_side=None,
            )
        ],
    )

    record_exchange_snapshot(
        captured_at=CAPTURED_AT,
        source="okx_ws",
        positions=[_position("pos-1", mark_px="232.00")],
    )

    card = position_cards().items[0]
    assert card.stop_status == "confirmed"
    assert card.stop_px == Decimal("220")
    assert card.mark_px == Decimal("232.00")


def test_spot_position_occupies_margin_at_one_times(client: TestClient) -> None:
    """现货没有杠杆不等于不占保证金：全额买入，占用就是名义本身。

    跳过多倍数字：一条名义 500、`lever` 为空的现货持仓，权益 1000 时占用率应当是
    50%，而不是 0%（把它当成「杠杆未知」而跳过）或 `≥0%`。
    """

    sync_instruments(parse_instruments([SWAP_INSTRUMENT]))
    record_exchange_snapshot(
        captured_at=CAPTURED_AT,
        source="okx_rest",
        snapshot=_snapshot("1000"),
        positions=[_position("pos-spot", lever="")],
    )

    view = account_summary()

    assert view.margin_used == Decimal("1851.36")
    assert view.margin_usage_pct == Decimal("185.136")
    # 价格齐全，所以不是下限
    assert view.margin_usage_floor is False


def test_manual_position_without_leverage_also_occupies_margin(client: TestClient) -> None:
    sync_instruments(parse_instruments([SWAP_INSTRUMENT]))
    # 手动持仓的价值按最新收盘价折算，先把行情落到库里。
    seed_daily("AAPL-USDT-SWAP", ["100"])
    record_exchange_snapshot(
        captured_at=CAPTURED_AT,
        source="okx_rest",
        snapshot=_snapshot("1000"),
        positions=[],
    )
    created = client.post(
        "/api/manual-positions",
        json={
            "inst_id": "AAPL-USDT-SWAP",
            "side": "long",
            "quantity": "2",
            "avg_cost": "100",
            "idempotency_key": "spot-margin-1",
        },
    )
    assert created.status_code == 201, created.text

    view = account_summary()

    assert view.margin_used == Decimal("200")
    assert view.margin_usage_floor is False

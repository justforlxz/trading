"""止损三态：有止损 / 确认无止损 / 未取到。

这一组断言的重点不是「有价位」，而是**失败不能被说成「没设止损」**。把第三种状态
合并进第二种，界面上就会出现「15 个持仓缺止损」这种污蔑用户的结论。
"""

from __future__ import annotations

from decimal import Decimal

from app.core import ExchangePosition, StopOrder
from app.positions.stops import (
    STOP_CONFIRMED,
    STOP_NONE,
    STOP_UNAVAILABLE,
    resolve_stop_states,
)


def _position(
    pos_id: str = "pos-1",
    *,
    inst_id: str = "AAPL-USDT-SWAP",
    pos_side: str = "long",
    mark_px: str | None = "100",
) -> ExchangePosition:
    return ExchangePosition(
        pos_id=pos_id,
        inst_id=inst_id,
        pos_side=pos_side,
        size=Decimal("1"),
        avg_px=Decimal("100"),
        mark_px=None if mark_px is None else Decimal(mark_px),
        upl=Decimal("0"),
        upl_ratio=Decimal("0"),
        lever=Decimal("3"),
        mgn_mode="isolated",
        liq_px=None,
        margin=Decimal("0"),
    )


def _stop(px: str | None, *, inst_id: str = "AAPL-USDT-SWAP", pos_side: str = "net") -> StopOrder:
    return StopOrder(
        inst_id=inst_id,
        order_id="algo-1",
        order_type="conditional",
        side="sell",
        stop_px=None if px is None else Decimal(px),
        pos_side=pos_side,
    )


def test_algo_stop_order_is_confirmed() -> None:
    states = resolve_stop_states([_position()], [_stop("90")], available=True)

    assert states["pos-1"].status == STOP_CONFIRMED
    assert states["pos-1"].px == Decimal("90")


def test_order_carried_sl_trigger_px_is_confirmed() -> None:
    """普通订单上的 `slTriggerPx` 与策略委托走同一条结论路径。"""

    carried = StopOrder(
        inst_id="AAPL-USDT-SWAP",
        order_id="ord-1",
        order_type="limit",
        side="sell",
        stop_px=Decimal("95"),
        pos_side=None,
    )

    states = resolve_stop_states([_position()], [carried], available=True)

    assert states["pos-1"].status == STOP_CONFIRMED
    assert states["pos-1"].px == Decimal("95")


def test_no_stop_at_all_is_confirmed_none() -> None:
    states = resolve_stop_states([_position()], [], available=True)

    assert states["pos-1"].status == STOP_NONE
    assert states["pos-1"].px is None


def test_failed_fetch_is_unavailable_not_none() -> None:
    states = resolve_stop_states([_position()], [], available=False)

    assert states["pos-1"].status == STOP_UNAVAILABLE
    assert states["pos-1"].px is None


def test_take_profit_only_order_does_not_count_as_a_stop() -> None:
    states = resolve_stop_states([_position()], [_stop(None)], available=True)

    assert states["pos-1"].status == STOP_NONE


def test_stop_on_the_other_side_does_not_cover_this_position() -> None:
    states = resolve_stop_states(
        [_position(pos_side="long")],
        [_stop("90", pos_side="short")],
        available=True,
    )

    assert states["pos-1"].status == STOP_NONE


def test_multiple_stops_pick_the_one_closest_to_the_mark() -> None:
    states = resolve_stop_states(
        [_position(mark_px="100")],
        [_stop("60"), _stop("97"), _stop("99")],
        available=True,
    )

    assert states["pos-1"].px == Decimal("99")


def test_multiple_stops_without_a_mark_price_pick_the_lowest() -> None:
    states = resolve_stop_states(
        [_position(mark_px=None)],
        [_stop("97"), _stop("60")],
        available=True,
    )

    assert states["pos-1"].px == Decimal("60")


def test_each_position_gets_its_own_symbols_stop() -> None:
    positions = [
        _position("pos-1", inst_id="AAPL-USDT-SWAP"),
        _position("pos-2", inst_id="BTC-USDT-SWAP"),
    ]

    states = resolve_stop_states(positions, [_stop("90")], available=True)

    assert states["pos-1"].status == STOP_CONFIRMED
    assert states["pos-2"].status == STOP_NONE

"""risk 段改成批量取数后，四种数据下的结果与逐标的取数一致。

期望值都从「库里写了哪几根日线」反推：日线序列用恒定真实波幅构造，`ATR(14)`
因此恰好等于给定值；`atr_distance` 是价格距离除以 ATR，可以直接对上手算结果。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core import AccountSnapshot, Bar, ExchangePosition, Timeframe
from app.instrument import okx_source, sync_instruments
from app.market import latest_candle, upsert_candles
from app.positions import (
    create_manual_position,
    list_manual_positions,
    record_exchange_snapshot,
)
from app.risk import exposure_report, save_position_risk_config
from tests.factories.instruments import make_ref, make_swap_ref

D = Decimal
CAPTURED_AT = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
LAST_DAY = datetime(2026, 11, 12, 16, 0, tzinfo=UTC)
ATR_COUNT = 15


def _seed_swap(inst_id: str) -> None:
    sync_instruments([make_swap_ref(inst_id=inst_id)])


def _seed_spot(inst_id: str) -> None:
    sync_instruments([make_ref(inst_id=inst_id)])


def _constant_range_series(
    inst_id: str,
    *,
    close: str,
    atr: str,
    source: str,
    count: int = ATR_COUNT,
) -> None:
    """`count` 根日线，真实波幅恒定等于 `atr`，收盘价恒定等于 `close`。

    第一根没有前收盘，真实波幅按高低差算，所以高低差也取 `atr`；
    之后高低差 `atr`、与昨收的跳空为 0，真实波幅仍是 `atr`。ATR(14) 因此等于 `atr`。
    """

    price = D(close)
    half = D(atr) / 2
    opens = [LAST_DAY - timedelta(days=count - 1 - index) for index in range(count)]
    upsert_candles(
        [
            Bar(
                inst_id=inst_id,
                timeframe=Timeframe.parse("1d"),
                open_time=open_time,
                open=price,
                high=price + half,
                low=price - half,
                close=price,
                volume=D("10"),
                confirm=True,
                source=source,
            )
            for open_time in opens
        ]
    )


def _record_exchange(positions: list[ExchangePosition]) -> None:
    record_exchange_snapshot(
        captured_at=CAPTURED_AT,
        source="okx_rest",
        snapshot=AccountSnapshot(
            currency="USDT",
            equity=D("1000"),
            available_equity=D("1000"),
            cash_balance=D("1000"),
            unrealized_pnl=D("0"),
            used_margin=D("0"),
            available_margin=D("1000"),
            margin_ratio=D("0"),
        ),
        positions=positions,
    )


def _position(pos_id: str, inst_id: str, *, mark: str | None = "231.42") -> ExchangePosition:
    return ExchangePosition(
        pos_id=pos_id,
        inst_id=inst_id,
        pos_side="long",
        size=D("8"),
        avg_px=D("226.80"),
        mark_px=None if mark is None else D(mark),
        upl=D("0"),
        upl_ratio=D("0"),
        lever=D("3"),
        mgn_mode="cross",
        liq_px=None,
        margin=None,
    )


def _exposure_position(ref: str):  # type: ignore[no-untyped-def]
    """按持仓引用取出敞口里的一行；编号方式与 `app.risk` 的口径一致。"""

    return next(item for item in exposure_report().positions if item.position_ref == ref)


def test_position_without_daily_bars_keeps_mark_and_leaves_atr_empty() -> None:
    """持仓标的没有日线：价格仍用快照上的标记价，ATR 留空。"""

    _seed_swap("AAPL-USDT-SWAP")
    _record_exchange([_position("1", "AAPL-USDT-SWAP")])

    position = _exposure_position("exchange:okx-main:1")

    assert position.mark_px == D("231.42")
    assert position.atr_distance is None
    assert position.notional == D("8") * D("231.42")


def test_proxy_source_is_not_mixed_into_okx_prices_and_atr() -> None:
    """同一标的 OKX 与代理两种来源都有数据：最新价与 ATR 只认 OKX。"""

    _seed_swap("AAPL-USDT-SWAP")
    source = okx_source("SWAP")
    _constant_range_series("AAPL-USDT-SWAP", close="231.42", atr="2", source=source)
    # 代理来源的日线更新、价格更高、波幅更大：混用会立刻改变下面的两个断言。
    upsert_candles(
        [
            Bar(
                inst_id="AAPL-USDT-SWAP",
                timeframe=Timeframe.parse("1d"),
                open_time=LAST_DAY + timedelta(days=1),
                open=D("400"),
                high=D("450"),
                low=D("350"),
                close=D("400"),
                volume=D("10"),
                confirm=True,
                source="yahoo",
            )
        ]
    )
    _record_exchange([_position("2", "AAPL-USDT-SWAP", mark=None)])
    save_position_risk_config("exchange:okx-main:2", stop_px=D("230"))

    position = _exposure_position("exchange:okx-main:2")

    # 快照没有标记价，退回最新收盘价：必须是 OKX 那根 231.42，不是代理的 400。
    assert latest_candle("AAPL-USDT-SWAP", source="yahoo").close == D("400")
    assert position.mark_px == D("231.42")
    assert position.stop_distance_pct == (D("231.42") - D("230")) / D("231.42") * D("100")
    assert position.atr_distance == (D("231.42") - D("230")) / D("2")


def test_manual_position_without_exchange_data_uses_its_own_ledger() -> None:
    """手动持仓没有交易所数据：仍按账本与已落库行情给出价格，没有行情就留空。"""

    _seed_spot("SOL-USDT")
    _seed_spot("XNOBAR-USDT")
    _constant_range_series("SOL-USDT", close="120", atr="4", source=okx_source("SPOT"))
    with_candles = create_manual_position(
        inst_id="SOL-USDT",
        side="long",
        quantity=D("10"),
        avg_cost=D("100"),
        stop_px=D("90"),
        leverage=None,
        note=None,
        idempotency_key="manual-with-candles",
    )
    without_candles = create_manual_position(
        inst_id="XNOBAR-USDT",
        side="long",
        quantity=D("5"),
        avg_cost=D("10"),
        stop_px=None,
        leverage=None,
        note=None,
        idempotency_key="manual-without-candles",
    )

    views = {item.id: item for item in list_manual_positions()}
    assert views[with_candles.id].price == D("120")
    assert views[with_candles.id].price_source == okx_source("SPOT")
    assert views[with_candles.id].market_value == D("1200")
    assert views[without_candles.id].price is None
    assert views[without_candles.id].price_status == "unavailable"

    exposed = {item.position_ref: item for item in exposure_report().positions}
    assert exposed[f"manual:{with_candles.id}"].mark_px == D("120")
    assert exposed[f"manual:{with_candles.id}"].atr_distance == (D("120") - D("90")) / D("4")
    assert exposed[f"manual:{without_candles.id}"].mark_px is None


def test_many_positions_read_in_batches_match_per_symbol_reads() -> None:
    """十个持仓标的：批量取回的标记价与 ATR 与逐个标的读取逐项相同。"""

    symbols = [f"SYM{index}-USDT-SWAP" for index in range(10)]
    expected: dict[str, tuple[Decimal, Decimal]] = {}
    for index, symbol in enumerate(symbols):
        _seed_swap(symbol)
        close = str(100 + index * 10)
        atr = str(2 + index)
        source = okx_source("SWAP")
        _constant_range_series(symbol, close=close, atr=atr, source=source)
        expected[symbol] = (D(close), D(atr))

    _record_exchange(
        [_position(str(index), symbol, mark=None) for index, symbol in enumerate(symbols)]
    )
    for index in range(10):
        save_position_risk_config(f"exchange:okx-main:{index}", stop_px=D("50"))

    exposure = exposure_report()
    assert len(exposure.positions) == 10
    for position in exposure.positions:
        close, atr = expected[position.inst_id]
        assert position.mark_px == close
        assert position.atr_distance == (close - D("50")) / atr

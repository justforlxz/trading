"""手动持仓读数：标的与最新价改成按批读之后，来源优先级与缺失状态不变。

`PRICE_SOURCES` 是「同一标的有多个可信来源时先用哪一个」的唯一口径，与「哪一根最新」
不是一回事：本文件用一个更旧但优先级更高的来源把它钉住。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core import Bar, Timeframe
from app.instrument import sync_instruments
from app.market import upsert_candles
from app.positions import create_manual_position, list_manual_positions
from tests.factories.instruments import make_ref

D = Decimal
START = datetime(2026, 10, 1, 16, 0, tzinfo=UTC)
DAY = timedelta(days=1)


def _daily(symbol: str, close: str, *, offset: int, source: str) -> None:
    upsert_candles(
        [
            Bar(
                inst_id=symbol,
                timeframe=Timeframe.parse("1d"),
                open_time=START + DAY * offset,
                open=D(close),
                high=D(close),
                low=D(close),
                close=D(close),
                volume=D("1"),
                confirm=True,
                source=source,
            )
        ]
    )


def _manual(inst_id: str, key: str):  # type: ignore[no-untyped-def]
    return create_manual_position(
        inst_id=inst_id,
        side="long",
        quantity=D("10"),
        avg_cost=D("100"),
        stop_px=None,
        leverage=None,
        note=None,
        idempotency_key=key,
    )


def test_manual_position_price_keeps_source_priority_across_batch_reads() -> None:
    sync_instruments([make_ref(inst_id="XAAPL-USDT"), make_ref(inst_id="XMSFT-USDT")])
    # 优先级更高的 `okx` 只有更旧的一根，`okx_spot` 更新：取 90 而不是 100。
    _daily("XAAPL-USDT", "90", offset=0, source="okx")
    _daily("XAAPL-USDT", "100", offset=1, source="okx_spot")
    with_price = _manual("XAAPL-USDT", "with-price")
    without_price = _manual("XMSFT-USDT", "without-price")

    views = {item.id: item for item in list_manual_positions()}

    assert views[with_price.id].price == D("90")
    assert views[with_price.id].price_source == "okx"
    assert views[with_price.id].market_value == D("900")
    assert views[without_price.id].price is None
    assert views[without_price.id].price_status == "unavailable"
    assert views[without_price.id].market_value is None

"""保留策略（AC9）：1m/5m/15m 滚动 90 天，1h 及以上全量。"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.market.core.bars import ROLLING_BARS
from app.market.models import Candle
from app.market.retention import purge_rolling_candles
from tests.market.support import insert_instrument

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def _candle(instrument_id: int, bar: str, open_time: datetime) -> Candle:
    return Candle(
        instrument_id=instrument_id,
        bar=bar,
        open_time=open_time,
        open=Decimal("1"),
        high=Decimal("1"),
        low=Decimal("1"),
        close=Decimal("1"),
        vol=Decimal("1"),
        vol_ccy=Decimal("1"),
        vol_ccy_quote=Decimal("1"),
        confirm=True,
        source="okx_rest",
    )


async def test_purge_only_touches_rolling_bars(session) -> None:
    instrument = await insert_instrument(session)
    old = NOW - timedelta(days=120)
    recent = NOW - timedelta(days=1)
    for bar in ("1m", "5m", "15m", "1h", "4h", "1d"):
        session.add(_candle(instrument.id, bar, old))
        session.add(_candle(instrument.id, bar, recent))
    await session.commit()

    result = await purge_rolling_candles(session, retention_days=90, now=NOW)
    assert result.cutoff == NOW - timedelta(days=90)
    for bar in ROLLING_BARS:
        assert result.deleted_by_bar[bar] == 1
    assert result.deleted == 3

    remaining = {
        bar: await session.scalar(select(func.count()).select_from(Candle).where(Candle.bar == bar))
        for bar in ("1m", "5m", "15m", "1h", "4h", "1d")
    }
    assert remaining == {"1m": 1, "5m": 1, "15m": 1, "1h": 2, "4h": 2, "1d": 2}


async def test_purge_is_idempotent(session) -> None:
    instrument = await insert_instrument(session)
    session.add(_candle(instrument.id, "1m", NOW - timedelta(days=200)))
    await session.commit()

    first = await purge_rolling_candles(session, now=NOW)
    second = await purge_rolling_candles(session, now=NOW)
    assert first.deleted == 1
    assert second.deleted == 0

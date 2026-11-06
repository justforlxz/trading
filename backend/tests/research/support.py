"""research 测试辅助：造带波动的日线序列（恒定价格会让相关系数未定义）。"""

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.market.models import Candle, EquityAsset, EquityCandle
from tests.market.support import insert_instrument

START = datetime(2026, 9, 1, tzinfo=UTC)
ONE = Decimal("1")


def wave(
    count: int,
    *,
    offset: float = 100.0,
    amplitude: float = 5.0,
    step: float = 0.4,
) -> list[float]:
    """确定性波动序列（不用随机数，保证对拍可复现）。"""

    return [offset + amplitude * math.sin(index * step) for index in range(count)]


def inverted(values: list[float], *, offset: float = 200.0) -> list[float]:
    """把价格序列翻成反向相关（用于符号翻转用例，保持价格为正）。"""

    return [offset - value for value in values]


def _price(value: float) -> Decimal:
    return Decimal(repr(round(value, 6)))


def _okx_candle(instrument_id: int, bar: str, moment: datetime, close: float) -> Candle:
    price = _price(close)
    return Candle(
        instrument_id=instrument_id,
        bar=bar,
        open_time=moment,
        open=price,
        high=price,
        low=price,
        close=price,
        vol=ONE,
        vol_ccy=ONE,
        vol_ccy_quote=ONE,
        confirm=True,
        source="okx_rest",
    )


def _equity_candle(asset_id: int, interval: str, moment: datetime, close: float) -> EquityCandle:
    price = _price(close)
    return EquityCandle(
        equity_asset_id=asset_id,
        interval=interval,
        ts=moment,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=ONE,
        session="regular",
        source="yahoo",
    )


async def seed_okx_series(
    session: AsyncSession,
    series: dict[str, list[float]],
    *,
    bar: str = "1d",
    start: datetime = START,
) -> dict[str, int]:
    """按 `{inst_id: [close...]}` 落标的与日线；返回 `{inst_id: instrument_id}`。"""

    ids: dict[str, int] = {}
    for inst_id, closes in series.items():
        instrument = await insert_instrument(session, inst_id)
        ids[inst_id] = instrument.id
        session.add_all(
            [
                _okx_candle(instrument.id, bar, start + timedelta(days=index), close)
                for index, close in enumerate(closes)
            ]
        )
    await session.commit()
    return ids


async def seed_equity_series(
    session: AsyncSession,
    series: dict[str, list[float]],
    *,
    interval: str = "1d",
    start: datetime = START,
) -> dict[str, int]:
    """按 `{symbol: [close...]}` 落真实行情资产与日线；返回 `{symbol: equity_asset_id}`。"""

    ids: dict[str, int] = {}
    for symbol, closes in series.items():
        asset = EquityAsset(symbol=symbol, exchange="XNAS", mapping_status="mapped")
        session.add(asset)
        await session.flush()
        ids[symbol] = asset.id
        session.add_all(
            [
                _equity_candle(asset.id, interval, start + timedelta(days=index), close)
                for index, close in enumerate(closes)
            ]
        )
    await session.commit()
    return ids

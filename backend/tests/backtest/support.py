"""回测测试辅助：直接落策略行与 K 线，不经过网络。"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.market.core.bars import bar_seconds
from app.market.models import Candle
from app.strategy.models import Strategy, StrategyLeg

Leg = tuple[int, str, str]  # (instrument_id, side, target_weight)


async def seed_strategy(
    session: AsyncSession,
    legs: list[Leg],
    *,
    status: str = "approved",
    version: int = 1,
    name: str = "回测策略",
) -> Strategy:
    strategy = Strategy(
        strategy_key=f"key-{uuid4().hex}",
        name=name,
        kind="relative_value",
        status=status,
        templates=["momentum", "relative_strength"],
        params={},
        content_hash=f"hash-{uuid4().hex}",
        version=version,
    )
    session.add(strategy)
    await session.flush()
    for rank, (instrument_id, side, weight) in enumerate(legs):
        session.add(
            StrategyLeg(
                strategy_id=strategy.id,
                instrument_id=instrument_id,
                side=side,
                target_weight=Decimal(weight),
                rationale="test",
                rank=rank,
            )
        )
    await session.commit()
    await session.refresh(strategy)
    return strategy


async def seed_candles(
    session: AsyncSession,
    instrument_id: int,
    *,
    start: datetime,
    prices: list[str],
    bar: str = "1d",
    confirmed: list[bool] | None = None,
) -> None:
    step = bar_seconds(bar)
    flags = confirmed or [True] * len(prices)
    rows = []
    for index, price in enumerate(prices):
        value = Decimal(price)
        rows.append(
            Candle(
                instrument_id=instrument_id,
                bar=bar,
                open_time=start.replace(microsecond=0) + timedelta(seconds=step * index),
                open=value,
                high=value,
                low=value,
                close=value,
                vol=Decimal("1"),
                vol_ccy=Decimal("1"),
                vol_ccy_quote=Decimal("1"),
                confirm=flags[index],
                source="test",
            )
        )
    session.add_all(rows)
    await session.commit()


DAY = timedelta(days=1)


def at(day: int = 1, hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day, hours=hour)

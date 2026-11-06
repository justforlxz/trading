"""保留策略：滚动周期按天批量删除，长周期全量保留。

与 `data-model.md` §9 的偏差：文档原写「按月删除分区」，但 candle 按 `open_time`
单键分区时同一分区混有 1h/1d 等长周期数据，无法只清短周期。因此改为**不分区 +
按 bar 行级批量 DELETE**（每批 `batch_size` 行，避免长事务与锁膨胀）。
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.market.core.bars import ROLLING_BARS
from app.market.models import Candle

DEFAULT_BATCH_SIZE = 5000


@dataclass(frozen=True, slots=True)
class RetentionResult:
    cutoff: datetime
    deleted_by_bar: dict[str, int]

    @property
    def deleted(self) -> int:
        return sum(self.deleted_by_bar.values())


async def purge_rolling_candles(
    session: AsyncSession,
    *,
    retention_days: int = 90,
    now: datetime | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> RetentionResult:
    """删除 `ROLLING_BARS` 中早于 cutoff 的行；1h 及以上不动。"""

    moment = now or datetime.now(tz=UTC)
    cutoff = moment - timedelta(days=retention_days)
    deleted: dict[str, int] = {}
    for bar in ROLLING_BARS:
        total = 0
        while True:
            ids = list(
                await session.scalars(
                    select(Candle.id)
                    .where(Candle.bar == bar, Candle.open_time < cutoff)
                    .limit(batch_size)
                )
            )
            if not ids:
                break
            await session.execute(delete(Candle).where(Candle.id.in_(ids)))
            await session.commit()
            total += len(ids)
            if len(ids) < batch_size:
                break
        deleted[bar] = total
    return RetentionResult(cutoff=cutoff, deleted_by_bar=deleted)


__all__ = ["RetentionResult", "purge_rolling_candles"]

"""真实美股行情：标的映射、日线同步、缺失登记与基差快照。

原则（`docs/risk/external-dependencies.md` §2.9）：真实行情只作为关系分析与时段
交叉校验的基准；取不到就记 `MISSING_SOURCE`，绝不用 OKX 指数价冒充收盘价。
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.equity.base import EquitySourceUnavailable, EquitySymbolNotFound
from app.market import sync_status
from app.market.models import BasisSnapshot, EquityAsset, EquityCandle, Instrument
from app.ops.quality import record_issue, resolve_issues
from app.ports.market_data import EquityCandleRow, EquityQuote, EquitySource

DATASET_CANDLE = "market.equity_candle"
DATASET_BASIS = "market.basis"
ELIGIBLE_ASSET_CLASSES = ("us_equity", "etf")
BASIS_QUANT = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class EquitySyncResult:
    """一次真实行情同步的结果。"""

    assets: int
    candles_written: int
    missing: list[str]


def symbol_from_inst_id(inst_id: str) -> str:
    """`AAPL-USDT-SWAP` → `AAPL`。"""

    return inst_id.split("-", 1)[0]


async def ensure_equity_assets(session: AsyncSession, source: EquitySource) -> list[EquityAsset]:
    """把可参与相关性的标的（美股正股 + ETF）映射为 `market.equity_asset`。"""

    instruments = list(
        await session.scalars(
            select(Instrument).where(Instrument.asset_class.in_(ELIGIBLE_ASSET_CLASSES))
        )
    )
    now = datetime.now(tz=UTC)
    for instrument in instruments:
        symbol = symbol_from_inst_id(instrument.inst_id)
        statement = pg_insert(EquityAsset).values(
            symbol=symbol,
            exchange=instrument.exchange,
            currency="USD",
            timezone="America/New_York",
            source_symbol=symbol,
            source_name=source.name,
            mapping_status="mapped",
            created_at=now,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_equity_asset_symbol_exchange",
            set_={
                "source_symbol": statement.excluded.source_symbol,
                "source_name": statement.excluded.source_name,
                "mapping_status": statement.excluded.mapping_status,
            },
        )
        await session.execute(statement)
    await session.commit()
    return list(await session.scalars(select(EquityAsset).order_by(EquityAsset.symbol)))


async def upsert_equity_candles(
    session: AsyncSession, equity_asset_id: int, rows: list[EquityCandleRow]
) -> int:
    if not rows:
        return 0
    now = datetime.now(tz=UTC)
    payload = [
        {
            "equity_asset_id": equity_asset_id,
            "interval": row.interval,
            "ts": row.ts,
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "volume": row.volume,
            "session": row.session,
            "source": row.source,
            "ingested_at": now,
        }
        for row in rows
    ]
    statement = pg_insert(EquityCandle).values(payload)
    statement = statement.on_conflict_do_update(
        constraint="uq_equity_candle_key",
        set_={
            "open": statement.excluded.open,
            "high": statement.excluded.high,
            "low": statement.excluded.low,
            "close": statement.excluded.close,
            "volume": statement.excluded.volume,
            "session": statement.excluded.session,
            "source": statement.excluded.source,
            "ingested_at": statement.excluded.ingested_at,
        },
    )
    await session.execute(statement)
    await session.commit()
    return len(payload)


async def sync_equity_candles(
    session: AsyncSession,
    source: EquitySource,
    *,
    assets: list[EquityAsset] | None = None,
    lookback_days: int = 10,
    now: datetime | None = None,
) -> EquitySyncResult:
    """逐标的拉日线；单个标的失败只记问题，不中断整体同步。"""

    moment = now or datetime.now(tz=UTC)
    targets = assets if assets is not None else await ensure_equity_assets(session, source)
    bucket_start, bucket_end = sync_status.day_bucket(moment)
    written = 0
    missing: list[str] = []
    for asset in targets:
        symbol = asset.source_symbol or asset.symbol
        scope = f"{asset.symbol}:1d"
        try:
            rows = await source.fetch_daily(symbol, lookback_days=lookback_days)
        except (EquitySourceUnavailable, EquitySymbolNotFound) as error:
            missing.append(asset.symbol)
            # 以自然日为去重窗口：同一天连续失败只保留一行，不会每轮翻倍。
            await record_issue(
                session,
                dataset=DATASET_CANDLE,
                scope_id=scope,
                kind="MISSING_SOURCE",
                window_start=bucket_start,
                window_end=bucket_end,
                severity="warning",
                detail={
                    "symbol": asset.symbol,
                    "source": source.name,
                    "reason": str(error),
                },
            )
            await sync_status.record_sync(
                session,
                source=source.name,
                dataset=DATASET_CANDLE,
                scope=scope,
                window_start=bucket_start,
                window_end=bucket_end,
                status="failed",
                error=str(error),
            )
            continue
        written += await upsert_equity_candles(session, asset.id, rows)
        await resolve_issues(session, dataset=DATASET_CANDLE, scope_id=scope, kind="MISSING_SOURCE")
        await sync_status.record_sync(
            session,
            source=source.name,
            dataset=DATASET_CANDLE,
            scope=scope,
            window_start=bucket_start,
            window_end=bucket_end,
            status="ok",
            rows_written=len(rows),
        )
    await session.commit()
    return EquitySyncResult(assets=len(targets), candles_written=written, missing=missing)


def compute_basis_bps(okx_price: Decimal, equity_price: Decimal) -> Decimal:
    """合约相对真实股价的基差（基点）；真实价为 0 时视为 0，避免除零。"""

    if equity_price == 0:
        return Decimal("0")
    raw = (okx_price / equity_price - Decimal("1")) * Decimal("10000")
    return raw.quantize(BASIS_QUANT)


async def record_basis(
    session: AsyncSession,
    *,
    instrument: Instrument,
    okx_price: Decimal,
    quote: EquityQuote,
    alert_bps: int = 500,
) -> BasisSnapshot:
    """落一条基差快照；超过阈值时登记 OUTLIER 问题。"""

    symbol = symbol_from_inst_id(instrument.inst_id)
    basis = compute_basis_bps(okx_price, quote.price)
    statement = pg_insert(BasisSnapshot).values(
        instrument_id=instrument.id,
        symbol=symbol,
        ts=quote.ts,
        okx_price=okx_price,
        equity_price=quote.price,
        basis_bps=basis,
        source=quote.source,
        created_at=datetime.now(tz=UTC),
    )
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_basis_snapshot_key",
            set_={
                "okx_price": statement.excluded.okx_price,
                "equity_price": statement.excluded.equity_price,
                "basis_bps": statement.excluded.basis_bps,
                "source": statement.excluded.source,
            },
        )
    )
    if abs(basis) > Decimal(alert_bps):
        await record_issue(
            session,
            dataset=DATASET_BASIS,
            scope_id=instrument.inst_id,
            kind="OUTLIER",
            window_start=quote.ts,
            severity="warning",
            detail={
                "symbol": symbol,
                "okx_price": str(okx_price),
                "equity_price": str(quote.price),
                "basis_bps": str(basis),
                "threshold_bps": alert_bps,
            },
        )
    await session.commit()
    stored = await session.scalar(
        select(BasisSnapshot).where(
            BasisSnapshot.instrument_id == instrument.id, BasisSnapshot.ts == quote.ts
        )
    )
    if stored is None:  # pragma: no cover - 刚写入必然存在
        raise RuntimeError("basis snapshot lost after write")
    return stored


async def list_basis(
    session: AsyncSession, *, inst_id: str, limit: int = 50
) -> list[BasisSnapshot]:
    statement = (
        select(BasisSnapshot)
        .join(Instrument, Instrument.id == BasisSnapshot.instrument_id)
        .where(Instrument.inst_id == inst_id)
        .order_by(BasisSnapshot.ts.desc())
        .limit(limit)
    )
    return list(await session.scalars(statement))


async def list_equity_candles(
    session: AsyncSession,
    *,
    symbol: str,
    interval: str = "1d",
    limit: int = 200,
    cursor: datetime | None = None,
) -> tuple[list[EquityCandle], datetime | None]:
    statement = (
        select(EquityCandle)
        .join(EquityAsset, EquityAsset.id == EquityCandle.equity_asset_id)
        .where(EquityAsset.symbol == symbol, EquityCandle.interval == interval)
        .order_by(EquityCandle.ts)
        .limit(limit + 1)
    )
    if cursor is not None:
        statement = statement.where(EquityCandle.ts > cursor)
    rows = list(await session.scalars(statement))
    next_cursor = rows[limit - 1].ts if len(rows) > limit else None
    return rows[:limit], next_cursor


def asset_payload(asset: EquityAsset) -> dict[str, Any]:
    """API 输出用（不透传内部 id 之外的原始响应）。"""

    return {
        "symbol": asset.symbol,
        "exchange": asset.exchange,
        "currency": asset.currency,
        "timezone": asset.timezone,
        "source_symbol": asset.source_symbol,
        "source_name": asset.source_name,
        "mapping_status": asset.mapping_status,
    }

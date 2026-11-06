"""采集任务：arq worker 的实际执行体。

每个任务都遵循同一套生命周期：`ops.job_run` 标记 running → 执行 → 收敛为
ok / partial / failed。**任何上游失败都不会抛到 arq 的重试层之外**：限流耗尽
按 `partial` 收敛并登记缺口，只有未预期异常才记 failed。
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.adapters.equity.registry import build_equity_source
from app.adapters.okx.candles import OkxCandleSource
from app.adapters.okx.client import OkxClient
from app.adapters.okx.index import OkxSnapshotSource
from app.adapters.okx.instruments import OkxInstrumentSource
from app.adapters.okx.rate_limit import UpstreamUnavailable
from app.config import get_settings
from app.db.session import session_factory
from app.jobs import runs
from app.market import candles as candle_service
from app.market import equity as equity_service
from app.market import instruments as instrument_service
from app.market import retention as retention_service
from app.market import sessions as session_service
from app.market.core.bars import bar_seconds, parse_bars
from app.market.models import Candle, Instrument
from app.ops.quality import detect_price_jumps, is_stale, record_issue
from app.ports.market_data import CandleRow

logger = logging.getLogger(__name__)

SYNC_INSTRUMENTS = "sync_instruments"
INGEST_CANDLES = "ingest_candles"
BACKFILL_CANDLES = "backfill_candles"
SYNC_EQUITY = "sync_equity"
SYNC_SESSIONS = "sync_sessions"
QUALITY_SCAN = "quality_scan"
PURGE_ROLLING = "purge_rolling_candles"


def build_okx_client() -> OkxClient:
    settings = get_settings()
    return OkxClient(
        settings.okx_rest_base_url,
        settings.okx_http_timeout_seconds,
        candles_rate_limit=settings.okx_candles_rate_limit,
        history_rate_limit=settings.okx_history_rate_limit,
        window_seconds=settings.okx_rate_limit_window_seconds,
        max_retries=settings.okx_max_retries,
        backoff_seconds=settings.okx_retry_backoff_seconds,
    )


async def run_sync_instruments(session, source) -> dict[str, Any]:
    """标的同步的纯服务实现（不碰 job_run，便于单测直接调用）。"""

    result = await instrument_service.sync_instruments(session, source)
    return {
        "fetched": result.fetched,
        "inserted": result.inserted,
        "updated": result.updated,
        "by_asset_class": result.by_asset_class,
    }


async def run_ingest_candles(
    session,
    source,
    *,
    inst_ids: list[str] | None = None,
    bars: list[str] | None = None,
    limit: int = 300,
    now: datetime | None = None,
) -> dict[str, Any]:
    """增量采集若干标的；单个标的限流耗尽只记缺口，整体收敛 partial。"""

    settings = get_settings()
    targets = inst_ids or [
        item.strip() for item in settings.candle_ingest_symbols.split(",") if item.strip()
    ]
    selected_bars = bars or parse_bars(settings.ingest_bars)
    # 配置里写的是股票代码（AAPL），落库的是 inst_id（AAPL-USDT-SWAP）与
    # uly（AAPL-USDT），用 uly 的首段匹配，避免符号与 inst_id 混用。
    rows = list(await session.scalars(select(Instrument)))
    by_symbol = {row.uly.split("-", 1)[0]: row for row in rows if row.uly}
    instruments = [by_symbol[symbol] for symbol in targets if symbol in by_symbol]
    missing_instruments = sorted(set(targets) - set(by_symbol))
    written: dict[str, dict[str, int]] = {}
    failed: dict[str, str] = {}
    for instrument in instruments:
        try:
            written[instrument.inst_id] = await candle_service.ingest_recent(
                session, source, instrument=instrument, bars=selected_bars, limit=limit, now=now
            )
        except UpstreamUnavailable as error:
            failed[instrument.inst_id] = str(error)
            for bar in selected_bars:
                await candle_service.record_collection_gap(
                    session, instrument=instrument, bar=bar, now=now
                )

    status = "partial" if failed or missing_instruments else "ok"
    return {
        "status": status,
        "inst_ids": targets,
        "bars": selected_bars,
        "written": written,
        "failed": failed,
        "missing_instruments": missing_instruments,
    }


async def sync_instruments(ctx: dict[str, Any], run_id: int | None = None) -> dict[str, Any]:
    client = build_okx_client()
    try:
        async with session_factory() as session:
            if run_id is not None:
                await runs.mark_running(session, run_id)
            try:
                payload = await run_sync_instruments(session, OkxInstrumentSource(client))
            except Exception as error:
                logger.exception("sync_instruments failed")
                if run_id is not None:
                    await runs.finish_run(session, run_id, "failed", error=str(error))
                raise
            if run_id is not None:
                await runs.finish_run(session, run_id, "ok", result=payload)
            return payload
    finally:
        await client.aclose()


async def ingest_candles(
    ctx: dict[str, Any],
    run_id: int | None = None,
    inst_ids: list[str] | None = None,
    bars: list[str] | None = None,
) -> dict[str, Any]:
    client = build_okx_client()
    try:
        async with session_factory() as session:
            if run_id is not None:
                await runs.mark_running(session, run_id)
            try:
                payload = await run_ingest_candles(
                    session, OkxCandleSource(client), inst_ids=inst_ids, bars=bars
                )
            except Exception as error:
                logger.exception("ingest_candles failed")
                if run_id is not None:
                    await runs.finish_run(session, run_id, "failed", error=str(error))
                raise
            if run_id is not None:
                await runs.finish_run(session, run_id, payload["status"], result=payload)
            return payload
    finally:
        await client.aclose()


async def backfill_candles(
    ctx: dict[str, Any],
    *,
    inst_id: str,
    bar: str,
    start: datetime,
    end: datetime,
    run_id: int | None = None,
) -> dict[str, Any]:
    client = build_okx_client()
    try:
        async with session_factory() as session:
            if run_id is not None:
                await runs.mark_running(session, run_id)
            instrument = await instrument_service.get_instrument(session, inst_id)
            if instrument is None:
                message = f"unknown inst_id: {inst_id}"
                if run_id is not None:
                    await runs.finish_run(session, run_id, "failed", error=message)
                raise ValueError(message)
            try:
                result = await candle_service.backfill(
                    session,
                    OkxCandleSource(client),
                    instrument=instrument,
                    bar=bar,
                    start=start,
                    end=end,
                )
            except Exception as error:
                logger.exception("backfill_candles failed")
                if run_id is not None:
                    await runs.finish_run(session, run_id, "failed", error=str(error))
                raise
            payload = {
                "inst_id": result.inst_id,
                "bar": result.bar,
                "rows_written": result.rows_written,
                "gaps": [
                    {"window_start": start_.isoformat(), "window_end": end_.isoformat()}
                    for start_, end_ in result.gaps
                ],
            }
            if run_id is not None:
                await runs.finish_run(session, run_id, result.status, result=payload)
            return payload
    finally:
        await client.aclose()


async def run_sync_equity(session, source) -> dict[str, Any]:
    mapped = await equity_service.ensure_equity_assets(session, source)
    settings = get_settings()
    wanted = {item.strip() for item in settings.equity_sync_symbols.split(",") if item.strip()}
    assets = [asset for asset in mapped if not wanted or asset.symbol in wanted]
    result = await equity_service.sync_equity_candles(
        session, source, assets=assets, lookback_days=settings.equity_daily_lookback_days
    )
    client = build_okx_client()
    okx = OkxSnapshotSource(client)
    recorded = 0
    for asset in assets:
        instrument = await session.scalar(
            select(Instrument).where(
                Instrument.inst_id.like(f"{asset.symbol}-%"),
                Instrument.asset_class.in_(["us_equity", "etf"]),
            )
        )
        if instrument is None:
            continue
        try:
            quote = await source.fetch_quote(asset.source_symbol or asset.symbol)
            snapshot = await okx.fetch_last_price(instrument.inst_id)
        except UpstreamUnavailable:
            continue
        if quote is None or snapshot is None:
            continue
        price, _ = snapshot
        await equity_service.record_basis(
            session,
            instrument=instrument,
            okx_price=price,
            quote=quote,
            alert_bps=settings.basis_alert_bps,
        )
        recorded += 1
    await client.aclose()
    return {
        "assets": result.assets,
        "candles_written": result.candles_written,
        "missing": result.missing,
        "basis_recorded": recorded,
        "status": "partial" if result.missing else "ok",
    }


async def sync_equity(ctx: dict[str, Any], run_id: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    source = build_equity_source(
        settings.equity_source, timeout_seconds=settings.equity_http_timeout_seconds
    )
    try:
        async with session_factory() as session:
            if run_id is not None:
                await runs.mark_running(session, run_id)
            try:
                payload = await run_sync_equity(session, source)
            except Exception as error:
                logger.exception("sync_equity failed")
                if run_id is not None:
                    await runs.finish_run(session, run_id, "failed", error=str(error))
                raise
            if run_id is not None:
                await runs.finish_run(session, run_id, payload["status"], result=payload)
            return payload
    finally:
        close = getattr(source, "aclose", None)
        if close is not None:
            await close()


async def sync_sessions(
    ctx: dict[str, Any], run_id: int | None = None, *, days_ahead: int = 30
) -> dict[str, Any]:
    today = datetime.now(tz=UTC).date()
    start = today - timedelta(days=7)
    end = today + timedelta(days=days_ahead)
    async with session_factory() as session:
        if run_id is not None:
            await runs.mark_running(session, run_id)
        result = await session_service.sync_sessions(session, start=start, end=end)
        payload = {
            "from": result.from_date.isoformat(),
            "to": result.to_date.isoformat(),
            "written": result.written,
            "trading_days": result.trading_days,
        }
        if run_id is not None:
            await runs.finish_run(session, run_id, "ok", result=payload)
        return payload


async def run_quality_scan(session, *, now: datetime | None = None) -> dict[str, Any]:
    """跳变 + 陈旧检查（缺口由采集时登记，避免重复扫全表）。"""

    moment = now or datetime.now(tz=UTC)
    # 只检查真正有数据的 (标的, 周期)，否则会把整张标的表都标成 STALE。
    pairs = list(await session.execute(select(Candle.instrument_id, Candle.bar).distinct()))
    by_id = {
        row.id: row
        for row in await session.scalars(
            select(Instrument).where(
                Instrument.id.in_({instrument_id for instrument_id, _ in pairs})
            )
        )
    }
    outliers = 0
    stale = 0
    checked = 0
    for instrument_id, bar in pairs:
        instrument = by_id.get(instrument_id)
        if instrument is None:
            continue
        checked += 1
        latest = await candle_service.latest_open_time(session, instrument.id, bar)
        if is_stale(latest, moment, bar_seconds(bar)):
            stale += 1
            await record_issue(
                session,
                dataset=candle_service.DATASET,
                scope_id=f"{instrument.inst_id}:{bar}",
                kind="STALE",
                window_start=latest or moment,
                severity="warning",
                detail={"inst_id": instrument.inst_id, "bar": bar},
            )
        if latest is None:
            continue
        rows, _ = await candle_service.list_candles(
            session, inst_id=instrument.inst_id, bar=bar, limit=200
        )
        for outlier in detect_price_jumps([_as_dto(row) for row in rows]):
            outliers += 1
            await record_issue(
                session,
                dataset=candle_service.DATASET,
                scope_id=f"{instrument.inst_id}:{bar}",
                kind="OUTLIER",
                window_start=outlier.open_time,
                severity="warning",
                detail={
                    "inst_id": instrument.inst_id,
                    "bar": bar,
                    "ratio": outlier.ratio,
                    "previous_close": str(outlier.previous_close),
                    "close": str(outlier.close),
                },
            )
    await session.commit()
    return {"pairs": checked, "outliers": outliers, "stale": stale}


def _as_dto(row) -> CandleRow:
    return CandleRow(
        inst_id="",
        bar=row.bar,
        open_time=row.open_time,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        vol=row.vol,
        vol_ccy=row.vol_ccy,
        vol_ccy_quote=row.vol_ccy_quote,
        confirm=row.confirm,
        source=row.source,
    )


async def quality_scan(ctx: dict[str, Any], run_id: int | None = None) -> dict[str, Any]:
    async with session_factory() as session:
        if run_id is not None:
            await runs.mark_running(session, run_id)
        payload = await run_quality_scan(session)
        if run_id is not None:
            await runs.finish_run(session, run_id, "ok", result=payload)
        return payload


async def purge_rolling_candles(ctx: dict[str, Any], run_id: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    async with session_factory() as session:
        if run_id is not None:
            await runs.mark_running(session, run_id)
        result = await retention_service.purge_rolling_candles(
            session, retention_days=settings.rolling_retention_days
        )
        payload = {
            "cutoff": result.cutoff.isoformat(),
            "deleted_by_bar": result.deleted_by_bar,
            "deleted": result.deleted,
        }
        if run_id is not None:
            await runs.finish_run(session, run_id, "ok", result=payload)
        return payload


TASK_FUNCTIONS = [
    sync_instruments,
    ingest_candles,
    backfill_candles,
    sync_equity,
    sync_sessions,
    quality_scan,
    purge_rolling_candles,
]

__all__ = [
    "BACKFILL_CANDLES",
    "INGEST_CANDLES",
    "PURGE_ROLLING",
    "QUALITY_SCAN",
    "SYNC_EQUITY",
    "SYNC_INSTRUMENTS",
    "SYNC_SESSIONS",
    "TASK_FUNCTIONS",
    "build_okx_client",
    "run_ingest_candles",
    "run_quality_scan",
    "run_sync_equity",
    "run_sync_instruments",
]

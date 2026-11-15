"""OKX 标的与历史 K 线的产品入口：一次调用完成取数、落库与任务流水。

单进程部署没有独立 worker，两个同步都在调用线程内完成，每次执行前后各写一行
`data_sync_jobs`。失败时先把错误写进任务流水再抛出，健康接口因此能读到真实结果，
而不是只看到一个没有结束的任务。

K 线同步不猜标的：请求里给的标识先查标的表，没同步过就明确报错；不传标识时按
设置里的订阅清单，再退回自选。这样「同步标的 → 加入自选 → 同步 K 线」是产品内
可以走通的路径，不需要手工写数据库。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from app.core import Clock, MarketDataPort, SystemClock, ValidationError
from app.exchange import ExchangeError, create_market_data
from app.instrument import (
    Instrument,
    list_instruments,
    okx_source,
    sync_instruments,
    trading_categories,
)
from app.market import (
    SyncJobView,
    finish_sync_job,
    start_sync_job,
    sync_candles,
)
from app.settings import load_settings
from app.shared import normalize_bar
from app.watchlist import tracked_instruments

__all__ = [
    "CANDLES_DATASET",
    "DEFAULT_CANDLE_BAR",
    "DEFAULT_CANDLE_DAYS",
    "INSTRUMENTS_DATASET",
    "MAX_CANDLE_DAYS",
    "OKX_PROVIDER",
    "SYNC_DATASETS",
    "run_candle_sync",
    "run_instrument_sync",
]

OKX_PROVIDER = "okx"
INSTRUMENTS_DATASET = "instruments"
CANDLES_DATASET = "candles"
SYNC_DATASETS: tuple[str, ...] = (INSTRUMENTS_DATASET, CANDLES_DATASET)

DEFAULT_CANDLE_BAR = "1d"
DEFAULT_CANDLE_DAYS = 30
MAX_CANDLE_DAYS = 3650


def run_instrument_sync(
    *,
    port: MarketDataPort | None = None,
    clock: Clock | None = None,
) -> SyncJobView:
    """同步 OKX 两类标的并写任务流水；返回结束后重新读到的任务视图。"""

    job = start_sync_job(OKX_PROVIDER, INSTRUMENTS_DATASET, clock=clock)
    owned = False
    market_port = port
    try:
        if market_port is None:
            market_port = create_market_data()
            owned = True
        refs = []
        for category in trading_categories():
            refs.extend(market_port.instruments(category))
        report = sync_instruments(refs)
    except Exception as exc:
        _record_failure(job.id, exc, clock=clock)
        raise
    finally:
        if owned and market_port is not None:
            market_port.close()
    return finish_sync_job(job.id, "succeeded", rows=report.inserted, clock=clock)


def run_candle_sync(
    instrument_ids: Sequence[str] = (),
    *,
    bar: str = DEFAULT_CANDLE_BAR,
    days: int = DEFAULT_CANDLE_DAYS,
    port: MarketDataPort | None = None,
    clock: Clock | None = None,
) -> SyncJobView:
    """按标的与周期同步一段历史 K 线并写任务流水。

    `instrument_ids` 为空时使用设置里的订阅清单，仍为空则使用自选。给的标识可以是
    交易所标识（`XAAPL-USDT`）或产品键（`AAPL`）；产品键会匹配到该产品的全部形态，
    两种形态本来就是两条独立的行情序列。
    """

    canonical = _normalize_bar(bar)
    if isinstance(days, bool) or not isinstance(days, int):
        raise ValidationError(f"同步天数必须是整数, 实际 {days!r}")
    if not 1 <= days <= MAX_CANDLE_DAYS:
        raise ValidationError(f"同步天数必须在 1..{MAX_CANDLE_DAYS} 之间, 实际 {days}")

    instruments = _resolve_instruments(instrument_ids)
    end = (clock or SystemClock()).now().replace(microsecond=0)
    start = end - timedelta(days=days)

    job = start_sync_job(OKX_PROVIDER, CANDLES_DATASET, clock=clock)
    owned = False
    market_port = port
    written = 0
    try:
        if market_port is None:
            market_port = create_market_data()
            owned = True
        for instrument in instruments:
            result = sync_candles(
                market_port,
                instrument.symbol,
                canonical,
                start,
                end,
                inst_type=instrument.inst_type,
                asset_type=instrument.asset_type,
                source=okx_source(instrument.inst_type),
            )
            written += result.inserted + result.updated
    except Exception as exc:
        _record_failure(job.id, exc, clock=clock)
        raise
    finally:
        if owned and market_port is not None:
            market_port.close()
    return finish_sync_job(job.id, "succeeded", rows=written, clock=clock)


def _normalize_bar(bar: str) -> str:
    try:
        return normalize_bar(bar)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def _resolve_instruments(tokens: Sequence[str]) -> tuple[Instrument, ...]:
    """把请求里的标识展开成标的行；不传时读取订阅清单与自选。"""

    selected = [token for token in tokens if isinstance(token, str) and token.strip()]
    if not selected:
        selected = _subscribed_tokens() or [
            instrument.symbol for instrument in tracked_instruments()
        ]
    if not selected:
        raise ValidationError("没有要同步的标的; 请给 instrument_ids, 或在设置里订阅标的")

    known = list_instruments()
    by_symbol = {row.symbol.upper(): row for row in known}
    resolved: dict[str, Instrument] = {}
    for token in selected:
        raw = token.strip().upper()
        if not raw:
            continue
        exact = by_symbol.get(raw)
        if exact is not None:
            resolved.setdefault(exact.symbol, exact)
            continue
        matches = [row for row in known if row.product_key.upper() == raw]
        if not matches:
            raise ValidationError(f"未找到标的 {token}; 请先同步标的")
        for row in matches:
            resolved.setdefault(row.symbol, row)
    if not resolved:
        raise ValidationError("没有要同步的标的; 请给 instrument_ids, 或在设置里订阅标的")
    return tuple(resolved.values())


def _subscribed_tokens() -> list[str]:
    subscribed = load_settings().data_sources.get("subscribed_instruments", [])
    if not isinstance(subscribed, list):
        return []
    return [item.strip() for item in subscribed if isinstance(item, str) and item.strip()]


def _record_failure(job_id: str, exc: Exception, *, clock: Clock | None) -> None:
    """把可预期的上游错误写原文，其余只记类型名，避免把连接串带进任务流水。"""

    expected = isinstance(exc, (ExchangeError, ValidationError))
    error = str(exc) if expected else type(exc).__name__
    finish_sync_job(job_id, "failed", error=error, clock=clock)

"""相对强弱快照（P1-09）：读序列、调纯函数、按 `run_key` 幂等落库。

同一套价格口径约束与关系快照一致：`okx_close` 只用合约 K 线，
`equity_close` 只用真实行情，缺失就明确说明，不做混用。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.core.relative_strength import RelativeStrength, compute, ratio_series
from app.market.models import Candle, EquityAsset, EquityCandle, Instrument
from app.research.models import RelativeStrengthSnapshot, TargetSymbol
from app.research.relations import (
    DEFAULT_BAR,
    RATIO_QUANT,
    SeriesPoint,
    target_equity_series,
    target_okx_series,
)

DEFAULT_MOMENTUM_DIVISOR = 5


def _decimal(value: float | None) -> str | None:
    if value is None:
        return None
    return str(Decimal(repr(value)).quantize(RATIO_QUANT))


def _run_key(
    *,
    target_id: int,
    counterparty_id: int,
    as_of: datetime,
    lookback_bars: int,
    price_basis: str,
    momentum_bars: int,
) -> str:
    payload = {
        "target_id": target_id,
        "counterparty_id": counterparty_id,
        "as_of": as_of.isoformat(),
        "lookback_bars": lookback_bars,
        "price_basis": price_basis,
        "momentum_bars": momentum_bars,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def _counterparty_okx_series(
    session: AsyncSession, *, instrument: Instrument, limit: int
) -> list[SeriesPoint]:
    statement = (
        select(Candle.open_time, Candle.close)
        .where(Candle.instrument_id == instrument.id, Candle.bar == DEFAULT_BAR)
        .order_by(Candle.open_time.desc())
        .limit(limit)
    )
    rows = list(await session.execute(statement))
    rows.reverse()
    return [(row[0], float(row[1])) for row in rows]


async def _counterparty_equity_series(
    session: AsyncSession, *, instrument: Instrument, limit: int
) -> list[SeriesPoint]:
    symbol = instrument.uly.split("-", 1)[0] if instrument.uly else instrument.inst_id
    statement = (
        select(EquityCandle.ts, EquityCandle.close)
        .join(EquityAsset, EquityAsset.id == EquityCandle.equity_asset_id)
        .where(EquityAsset.symbol == symbol, EquityCandle.interval == DEFAULT_BAR)
        .order_by(EquityCandle.ts.desc())
        .limit(limit)
    )
    rows = list(await session.execute(statement))
    rows.reverse()
    return [(row[0], float(row[1])) for row in rows]


def _payload(
    result: RelativeStrength,
    *,
    target: TargetSymbol,
    counterparty: Instrument,
    aligned: list[tuple[float, float]],
    timestamps: list[datetime],
    lookback_bars: int,
    momentum_bars: int,
    price_basis: str,
) -> dict[str, Any]:
    series_payload: list[dict[str, Any]] = []
    if result.defined:
        ratios = ratio_series([value for value, _ in aligned], [value for _, value in aligned])
        if ratios is not None:
            series_payload = [
                {"ts": timestamp.isoformat(), "rs_ratio": _decimal(ratio)}
                for timestamp, ratio in zip(timestamps, ratios, strict=True)
            ]
    return {
        "defined": result.defined,
        "reason": result.reason,
        "target": {"id": target.id, "symbol": target.symbol, "exchange": target.exchange},
        "counterparty": {
            "inst_id": counterparty.inst_id,
            "symbol": counterparty.uly.split("-", 1)[0] if counterparty.uly else None,
        },
        "price_basis": price_basis,
        "lookback_bars": lookback_bars,
        "momentum_bars": momentum_bars,
        "as_of": timestamps[-1].isoformat() if timestamps else None,
        "rs_ratio": _decimal(result.rs_ratio),
        "rs_momentum": _decimal(result.rs_momentum),
        "momentum_reason": result.momentum_reason,
        "target_return": _decimal(result.target_return),
        "counterparty_return": _decimal(result.counterparty_return),
        "excess_return": _decimal(result.excess_return),
        "trend": result.trend,
        "series": series_payload,
    }


async def compute_relative_strength(
    session: AsyncSession,
    *,
    target: TargetSymbol,
    counterparty: Instrument,
    lookback: int,
    price_basis: str = "okx_close",
    momentum_bars: int | None = None,
) -> dict[str, Any]:
    """计算相对强弱并把已定义的结果按 `run_key` 幂等落库。"""

    resolved_momentum = momentum_bars or max(1, lookback // DEFAULT_MOMENTUM_DIVISOR)
    if price_basis == "equity_close":
        target_series = await target_equity_series(
            session, target=target, limit=lookback, as_of=None
        )
        counterparty_series = await _counterparty_equity_series(
            session, instrument=counterparty, limit=lookback
        )
        missing_reason = (
            f"MISSING_SOURCE: {target.symbol} 或 {counterparty.inst_id} 在 equity_close "
            "口径下没有真实行情, 先用 /market/backfill 回补"
        )
    else:
        target_series = await target_okx_series(
            session, target=target, bar=DEFAULT_BAR, limit=lookback, as_of=None
        )
        counterparty_series = await _counterparty_okx_series(
            session, instrument=counterparty, limit=lookback
        )
        missing_reason = (
            f"MISSING_SOURCE: {target.symbol} 或 {counterparty.inst_id} 在 "
            f"{DEFAULT_BAR} 上没有 K 线, 先用 /market/backfill 回补"
        )

    counterparty_index = dict(counterparty_series)
    kept = [
        (timestamp, value) for timestamp, value in target_series if timestamp in counterparty_index
    ]
    timestamps = [timestamp for timestamp, _ in kept]
    aligned = [(value, counterparty_index[timestamp]) for timestamp, value in kept]

    if len(aligned) < 2:
        return {
            "defined": False,
            "reason": missing_reason,
            "target": {"id": target.id, "symbol": target.symbol, "exchange": target.exchange},
            "counterparty": {
                "inst_id": counterparty.inst_id,
                "symbol": counterparty.uly.split("-", 1)[0] if counterparty.uly else None,
            },
            "price_basis": price_basis,
            "lookback_bars": lookback,
            "momentum_bars": resolved_momentum,
            "as_of": timestamps[-1].isoformat() if timestamps else None,
            "rs_ratio": None,
            "rs_momentum": None,
            "momentum_reason": None,
            "target_return": None,
            "counterparty_return": None,
            "excess_return": None,
            "trend": None,
            "series": [],
        }

    result = compute(
        [value for value, _ in aligned],
        [value for _, value in aligned],
        momentum_bars=resolved_momentum,
    )
    payload = _payload(
        result,
        target=target,
        counterparty=counterparty,
        aligned=aligned,
        timestamps=timestamps,
        lookback_bars=len(aligned),
        momentum_bars=resolved_momentum,
        price_basis=price_basis,
    )

    if result.defined:
        as_of = timestamps[-1]
        await session.execute(
            pg_insert(RelativeStrengthSnapshot)
            .values(
                target_id=target.id,
                counterparty_id=counterparty.id,
                as_of=as_of,
                lookback_bars=len(aligned),
                rs_ratio=Decimal(repr(result.rs_ratio or 0.0)).quantize(RATIO_QUANT),
                rs_momentum=Decimal(repr(result.rs_momentum or 0.0)).quantize(RATIO_QUANT),
                run_key=_run_key(
                    target_id=target.id,
                    counterparty_id=counterparty.id,
                    as_of=as_of,
                    lookback_bars=len(aligned),
                    price_basis=price_basis,
                    momentum_bars=resolved_momentum,
                ),
            )
            .on_conflict_do_nothing(index_elements=["run_key"])
        )
        await session.commit()

    return payload


__all__ = ["compute_relative_strength"]

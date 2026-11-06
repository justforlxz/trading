"""关系快照与显著变化（P1-08）。

编排职责：读行情序列 → 调 `app.analysis.core` 纯函数 → 幂等落库。
决策职责（相关性、滞后搜索、稳定性、显著变化判定）全部在纯函数里。

价格口径不混用：一次计算只用一个来源，`price_basis` 写进快照头，
`okx_close` 用 `market.candle`，`equity_close` 用 `market.equity_candle`；
真实行情缺失时显式返回 `MISSING_SOURCE`，绝不用 OKX 价格顶替。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.core.correlation import (
    MIN_SAMPLES,
    lagged_correlation,
    rolling_sign_agreement,
)
from app.analysis.core.relation_diff import significant_changes
from app.market.core.classification import CORRELATION_ASSET_CLASSES
from app.market.models import Candle, EquityAsset, EquityCandle, Instrument
from app.research.models import RelationEdge, RelationSnapshot, TargetSymbol

PRICE_BASES: tuple[str, ...] = ("okx_close", "equity_close")
METHODS: tuple[str, ...] = ("pearson", "spearman")
DEFAULT_BAR = "1d"
RATIO_QUANT = Decimal("0.0000000001")

STATUS_OK = "ok"
STATUS_SKIPPED = "skipped"
STATUS_UNDEFINED = "undefined"

SeriesPoint = tuple[datetime, float]


@dataclass(frozen=True, slots=True)
class ComputeOutcome:
    """一次重算的结果；`status` 与 `ops.job_run` 的状态对齐。"""

    status: str
    reason: str | None
    snapshot: RelationSnapshot | None
    edge_count: int

    @property
    def job_status(self) -> str:
        if self.status == STATUS_OK:
            return "ok"
        if self.status == STATUS_SKIPPED:
            return "skipped"
        return "partial"


def _ratio(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(repr(value)).quantize(RATIO_QUANT)


def compute_run_key(
    *,
    target_id: int,
    as_of: datetime,
    window_bars: int,
    method: str,
    price_basis: str,
) -> str:
    """派生结果的幂等键：口径身份（target/as_of/窗口/方法/价格来源）的 sha256。

    计算参数（`lag_max` / `stability_window` / `change_threshold`）不进键，
    只写进 `params`：它们必须与 `uq_relation_snapshot_business` 表达同一组语义，
    否则同一 `as_of` 改配置重算会撞上另一条唯一约束而不是得到 `skipped`。
    阈值本身在读取时按当前配置计算显著变化，因此改阈值无需重算快照。
    """

    payload = {
        "target_id": target_id,
        "as_of": as_of.isoformat(),
        "window_bars": window_bars,
        "method": method,
        "price_basis": price_basis,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def align_series(base: list[SeriesPoint], other: list[SeriesPoint]) -> list[tuple[float, float]]:
    """按时间戳内连接对齐（成交 24/7，但两个序列的起点可能不同）。"""

    index = dict(other)
    aligned: list[tuple[float, float]] = []
    for timestamp, value in base:
        counterparty_value = index.get(timestamp)
        if counterparty_value is not None:
            aligned.append((value, counterparty_value))
    return aligned


async def _instrument_ids_for_symbol(session: AsyncSession, symbol: str) -> list[int]:
    """按 `uly` 首段匹配 symbol，返回全部合约 id（同一标的可能有多条合约记录）。"""

    statement = (
        select(Instrument.id)
        .where(func.split_part(Instrument.uly, "-", 1) == symbol)
        .order_by(Instrument.id)
    )
    return list(await session.scalars(statement))


async def target_okx_series(
    session: AsyncSession,
    *,
    target: TargetSymbol,
    bar: str,
    limit: int,
    as_of: datetime | None,
) -> list[SeriesPoint]:
    instrument_id = target.instrument_id
    if instrument_id is None:
        # 历史数据里没有映射时按 symbol 再找一次，避免把「无合约」误判成「无行情」。
        resolved = await _instrument_ids_for_symbol(session, target.symbol)
        instrument_id = resolved[0] if resolved else None
    if instrument_id is None:
        return []
    statement = select(Candle.open_time, Candle.close).where(
        Candle.instrument_id == instrument_id, Candle.bar == bar
    )
    if as_of is not None:
        statement = statement.where(Candle.open_time <= as_of)
    statement = statement.order_by(Candle.open_time.desc()).limit(limit)
    rows = list(await session.execute(statement))
    rows.reverse()
    return [(row[0], float(row[1])) for row in rows]


async def target_equity_series(
    session: AsyncSession, *, target: TargetSymbol, limit: int, as_of: datetime | None
) -> list[SeriesPoint]:
    statement = (
        select(EquityCandle.ts, EquityCandle.close)
        .join(EquityAsset, EquityAsset.id == EquityCandle.equity_asset_id)
        .where(EquityAsset.symbol == target.symbol, EquityCandle.interval == DEFAULT_BAR)
    )
    if as_of is not None:
        statement = statement.where(EquityCandle.ts <= as_of)
    statement = statement.order_by(EquityCandle.ts.desc()).limit(limit)
    rows = list(await session.execute(statement))
    rows.reverse()
    return [(row[0], float(row[1])) for row in rows]


async def _candidate_instruments(
    session: AsyncSession, *, exclude_ids: Collection[int]
) -> list[Instrument]:
    statement = (
        select(Instrument)
        .where(Instrument.asset_class.in_(tuple(CORRELATION_ASSET_CLASSES)))
        .order_by(Instrument.inst_id)
    )
    if exclude_ids:
        statement = statement.where(Instrument.id.not_in(tuple(exclude_ids)))
    return list(await session.scalars(statement))


async def _okx_candidate_series(
    session: AsyncSession,
    *,
    instrument_ids: list[int],
    bar: str,
    start: datetime,
    end: datetime,
) -> dict[int, list[SeriesPoint]]:
    if not instrument_ids:
        return {}
    statement = (
        select(Candle.instrument_id, Candle.open_time, Candle.close)
        .where(
            Candle.instrument_id.in_(instrument_ids),
            Candle.bar == bar,
            Candle.open_time >= start,
            Candle.open_time <= end,
        )
        .order_by(Candle.instrument_id, Candle.open_time)
    )
    grouped: dict[int, list[SeriesPoint]] = {}
    for instrument_id, open_time, close in await session.execute(statement):
        grouped.setdefault(instrument_id, []).append((open_time, float(close)))
    return grouped


async def _equity_candidate_series(
    session: AsyncSession,
    *,
    symbols: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, list[SeriesPoint]]:
    if not symbols:
        return {}
    statement = (
        select(EquityAsset.symbol, EquityCandle.ts, EquityCandle.close)
        .join(EquityAsset, EquityAsset.id == EquityCandle.equity_asset_id)
        .where(
            EquityAsset.symbol.in_(symbols),
            EquityCandle.interval == DEFAULT_BAR,
            EquityCandle.ts >= start,
            EquityCandle.ts <= end,
        )
        .order_by(EquityAsset.symbol, EquityCandle.ts)
    )
    grouped: dict[str, list[SeriesPoint]] = {}
    for symbol, timestamp, close in await session.execute(statement):
        grouped.setdefault(symbol, []).append((timestamp, float(close)))
    return grouped


@dataclass(frozen=True, slots=True)
class _EdgeDraft:
    counterparty_id: int
    inst_id: str
    coefficient: float
    best_lag: int
    p_value: float | None
    stability: float | None


def _build_edges(
    candidates: list[tuple[Instrument, list[SeriesPoint]]],
    target_series: list[SeriesPoint],
    *,
    lag_max: int,
    stability_window: int,
    method: str,
    skipped: list[str],
) -> list[_EdgeDraft]:
    drafts: list[_EdgeDraft] = []
    for instrument, series in candidates:
        aligned = align_series(target_series, series)
        if len(aligned) < MIN_SAMPLES:
            skipped.append(instrument.inst_id)
            continue
        xs = [value for value, _ in aligned]
        ys = [value for _, value in aligned]
        lag = lagged_correlation(xs, ys, lag_max=lag_max, method=method)
        if not lag.defined:
            skipped.append(instrument.inst_id)
            continue
        window = min(stability_window, len(xs))
        stability = rolling_sign_agreement(xs, ys, window=window, method=method)
        drafts.append(
            _EdgeDraft(
                counterparty_id=instrument.id,
                inst_id=instrument.inst_id,
                coefficient=lag.coefficient or 0.0,
                best_lag=lag.best_lag or 0,
                p_value=lag.p_value,
                stability=stability,
            )
        )
    drafts.sort(key=lambda draft: (-abs(draft.coefficient), draft.inst_id))
    return drafts


async def compute_snapshot(
    session: AsyncSession,
    *,
    target: TargetSymbol,
    window_bars: int,
    method: str,
    price_basis: str,
    as_of: datetime | None = None,
    lag_max: int = 5,
    stability_window: int = 20,
    change_threshold: float = 0.2,
    bar: str = DEFAULT_BAR,
) -> ComputeOutcome:
    """计算并落库一次关系快照；同一 `run_key` 只落一次。"""

    if price_basis == "equity_close":
        target_series = await target_equity_series(
            session, target=target, limit=window_bars, as_of=as_of
        )
        missing_reason = (
            f"MISSING_SOURCE: {target.symbol} 在 equity_close 口径下没有真实行情"
            " (Yahoo 主源缺失), 先用 /market/backfill 回补或等待同步; 不会用 OKX 价格顶替"
        )
    else:
        target_series = await target_okx_series(
            session, target=target, bar=bar, limit=window_bars, as_of=as_of
        )
        missing_reason = (
            f"MISSING_SOURCE: {target.symbol} 在 {bar} 上没有 K 线, 先用 /market/backfill 回补"
        )

    if len(target_series) < MIN_SAMPLES:
        return ComputeOutcome(STATUS_UNDEFINED, missing_reason, None, 0)

    resolved_as_of = as_of if as_of is not None else target_series[-1][0]
    run_key = compute_run_key(
        target_id=target.id,
        as_of=resolved_as_of,
        window_bars=window_bars,
        method=method,
        price_basis=price_basis,
    )

    existing = await session.scalar(
        select(RelationSnapshot).where(RelationSnapshot.run_key == run_key)
    )
    if existing is not None:
        return ComputeOutcome(STATUS_SKIPPED, "snapshot_exists", existing, 0)

    start, end = target_series[0][0], target_series[-1][0]
    # 目标自身必须排除：`instrument_id` 允许为空（建目标时行情还没同步），
    # 此时按 symbol 解析出的合约会以候选身份参与，产生 r=1.0 的自环边。
    excluded_ids = set(await _instrument_ids_for_symbol(session, target.symbol))
    if target.instrument_id is not None:
        excluded_ids.add(target.instrument_id)
    instruments = await _candidate_instruments(session, exclude_ids=excluded_ids)
    skipped: list[str] = []
    candidates: list[tuple[Instrument, list[SeriesPoint]]] = []
    if price_basis == "equity_close":
        series_by_symbol = await _equity_candidate_series(
            session,
            symbols=[instrument.uly.split("-", 1)[0] for instrument in instruments],
            start=start,
            end=end,
        )
        for instrument in instruments:
            series = series_by_symbol.get(instrument.uly.split("-", 1)[0])
            if series:
                candidates.append((instrument, series))
    else:
        series_by_id = await _okx_candidate_series(
            session,
            instrument_ids=[instrument.id for instrument in instruments],
            bar=bar,
            start=start,
            end=end,
        )
        for instrument in instruments:
            series = series_by_id.get(instrument.id)
            if series:
                candidates.append((instrument, series))

    drafts = _build_edges(
        candidates,
        target_series,
        lag_max=lag_max,
        stability_window=stability_window,
        method=method,
        skipped=skipped,
    )

    params: dict[str, Any] = {
        "bar": bar,
        "lag_max": lag_max,
        "stability_window": stability_window,
        "change_threshold": change_threshold,
        "candidate_asset_classes": sorted(CORRELATION_ASSET_CLASSES),
        "candidates_total": len(instruments),
        "candidates_with_series": len(candidates),
        "skipped_no_data": sorted(skipped),
        "aligned_bars": len(target_series),
    }
    if not drafts:
        params["reason"] = "no_candidate_series_defined"

    insert_snapshot = (
        pg_insert(RelationSnapshot)
        .values(
            target_id=target.id,
            as_of=resolved_as_of,
            window_bars=window_bars,
            method=method,
            price_basis=price_basis,
            lag_max=lag_max,
            sample_size=len(target_series),
            run_key=run_key,
            params=params,
        )
        .on_conflict_do_nothing(index_elements=["run_key"])
        .returning(RelationSnapshot.id)
    )
    snapshot_id = await session.scalar(insert_snapshot)
    if snapshot_id is None:
        await session.rollback()
        existing = await session.scalar(
            select(RelationSnapshot).where(RelationSnapshot.run_key == run_key)
        )
        return ComputeOutcome(STATUS_SKIPPED, "snapshot_exists", existing, 0)

    if drafts:
        rows = [
            {
                "snapshot_id": snapshot_id,
                "counterparty_id": draft.counterparty_id,
                "coefficient": _ratio(draft.coefficient),
                "best_lag": draft.best_lag,
                "p_value": _ratio(draft.p_value),
                "stability": _ratio(draft.stability),
                "rank": rank,
            }
            for rank, draft in enumerate(drafts, start=1)
        ]
        await session.execute(
            pg_insert(RelationEdge)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["snapshot_id", "counterparty_id", "best_lag"])
        )
    await session.commit()

    snapshot = await session.get(RelationSnapshot, snapshot_id)
    assert snapshot is not None
    if not drafts:
        return ComputeOutcome(STATUS_UNDEFINED, params["reason"], snapshot, 0)
    return ComputeOutcome(STATUS_OK, None, snapshot, len(drafts))


async def latest_snapshot(
    session: AsyncSession, target_id: int, *, as_of: datetime | None = None
) -> RelationSnapshot | None:
    statement = select(RelationSnapshot).where(RelationSnapshot.target_id == target_id)
    if as_of is not None:
        statement = statement.where(RelationSnapshot.as_of <= as_of)
    statement = statement.order_by(
        RelationSnapshot.as_of.desc(), RelationSnapshot.computed_at.desc()
    ).limit(1)
    return await session.scalar(statement)


async def previous_snapshot(
    session: AsyncSession, snapshot: RelationSnapshot
) -> RelationSnapshot | None:
    """同一口径下的上一份快照（用于计算显著变化）。"""

    statement = (
        select(RelationSnapshot)
        .where(
            RelationSnapshot.target_id == snapshot.target_id,
            RelationSnapshot.window_bars == snapshot.window_bars,
            RelationSnapshot.method == snapshot.method,
            RelationSnapshot.price_basis == snapshot.price_basis,
            RelationSnapshot.as_of < snapshot.as_of,
        )
        .order_by(RelationSnapshot.as_of.desc())
        .limit(1)
    )
    return await session.scalar(statement)


async def load_edges(
    session: AsyncSession, snapshot_id: int
) -> list[tuple[RelationEdge, Instrument]]:
    statement = (
        select(RelationEdge, Instrument)
        .join(Instrument, Instrument.id == RelationEdge.counterparty_id)
        .where(RelationEdge.snapshot_id == snapshot_id)
        .order_by(RelationEdge.rank)
    )
    return [(edge, instrument) for edge, instrument in await session.execute(statement)]


async def snapshot_changes(
    session: AsyncSession, snapshot: RelationSnapshot, *, threshold: float
) -> list[dict[str, Any]]:
    previous = await previous_snapshot(session, snapshot)
    if previous is None:
        return []
    before = {
        instrument.inst_id: float(edge.coefficient)
        for edge, instrument in await load_edges(session, previous.id)
    }
    after = {
        instrument.inst_id: float(edge.coefficient)
        for edge, instrument in await load_edges(session, snapshot.id)
    }
    return [
        change.as_payload() for change in significant_changes(before, after, threshold=threshold)
    ]


def edge_payload(edge: RelationEdge, instrument: Instrument) -> dict[str, Any]:
    symbol = instrument.uly.split("-", 1)[0] if instrument.uly else instrument.inst_id
    return {
        "counterparty_inst_id": instrument.inst_id,
        "counterparty": {
            "symbol": symbol,
            "exchange": instrument.exchange,
            "asset_class": instrument.asset_class,
        },
        "coefficient": str(edge.coefficient),
        "best_lag": edge.best_lag,
        "p_value": None if edge.p_value is None else str(edge.p_value),
        "stability": None if edge.stability is None else str(edge.stability),
        "rank": edge.rank,
    }


def snapshot_payload(snapshot: RelationSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "target_id": snapshot.target_id,
        "as_of": snapshot.as_of.isoformat(),
        "window_bars": snapshot.window_bars,
        "method": snapshot.method,
        "price_basis": snapshot.price_basis,
        "lag_max": snapshot.lag_max,
        "sample_size": snapshot.sample_size,
        "run_key": snapshot.run_key,
        "computed_at": snapshot.computed_at.isoformat(),
        "params": snapshot.params,
    }


def relation_reason(snapshot: RelationSnapshot) -> str | None:
    value = snapshot.params.get("reason") if snapshot.params else None
    return value if isinstance(value, str) else None


async def build_relations_payload(
    session: AsyncSession, snapshot: RelationSnapshot, *, threshold: float
) -> dict[str, Any]:
    rows = await load_edges(session, snapshot.id)
    edges = [edge_payload(edge, instrument) for edge, instrument in rows]
    changes = await snapshot_changes(session, snapshot, threshold=threshold)
    return {
        "status": STATUS_OK if edges else STATUS_UNDEFINED,
        "reason": relation_reason(snapshot) if not edges else None,
        "snapshot": snapshot_payload(snapshot),
        "edges": edges,
        "significant_changes": changes,
    }


async def list_history(
    session: AsyncSession, target_id: int, *, limit: int = 20, threshold: float = 0.2
) -> list[dict[str, Any]]:
    statement = (
        select(RelationSnapshot)
        .where(RelationSnapshot.target_id == target_id)
        .order_by(RelationSnapshot.as_of.desc())
        .limit(limit)
    )
    snapshots = list(await session.scalars(statement))
    payloads: list[dict[str, Any]] = []
    for snapshot in snapshots:
        rows = await load_edges(session, snapshot.id)
        payloads.append(
            {
                **snapshot_payload(snapshot),
                "edge_count": len(rows),
                "significant_changes": await snapshot_changes(
                    session, snapshot, threshold=threshold
                ),
            }
        )
    return payloads


__all__ = [
    "DEFAULT_BAR",
    "METHODS",
    "PRICE_BASES",
    "STATUS_OK",
    "STATUS_SKIPPED",
    "STATUS_UNDEFINED",
    "ComputeOutcome",
    "align_series",
    "build_relations_payload",
    "compute_run_key",
    "compute_snapshot",
    "edge_payload",
    "latest_snapshot",
    "list_history",
    "load_edges",
    "relation_reason",
    "snapshot_payload",
    "target_equity_series",
    "target_okx_series",
]

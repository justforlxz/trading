"""全市场机会扫描（P1-11 / P1-12 / P1-13 的编排层）。

职责只有「取数 → 调纯函数 → 落库」：
- 特征计算在 `app.analysis.core.features`；
- 聚类在 `app.analysis.core.clustering`；
- 共振 / 相关性突变在 `app.analysis.core.resonance`；
- 机会打分与理由在 `app.analysis.core.opportunities`。

本模块不实现任何指标算法，也不从环境变量读阈值（`Settings` 由调用方注入），
以便同一批数据可以用不同参数复现。

幂等口径：`run_key = sha256(as_of + universe + 参数)`。同一 `run_key` 重跑**原地更新**
自身（先清子表再写），不会新增批次；这与 `data-model.md` §4「同一 as_of 重跑只更新
自身」一致。
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from math import log
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.core import features
from app.analysis.core.clustering import cluster
from app.analysis.core.features import Bar, CrossSection
from app.analysis.core.opportunities import (
    Candidate,
    MemberFeature,
    directional_candidates,
    market_breadth,
    pair_candidates,
)
from app.config import Settings, get_settings
from app.market.core.classification import PRIVATE_COMPANIES
from app.market.models import Candle, Instrument
from app.opportunity.models import (
    AssetCluster,
    ClusterMember,
    Opportunity,
    OpportunityRun,
)
from app.research.models import MarketSnapshot

INST_CATEGORY_US_STOCK = 3
STATUS_RUNNING = "running"
STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

RATIO_QUANT = Decimal("0.0000000001")

DEFAULT_PARAMS: dict[str, Any] = {
    "bar": "1d",
    "lookback_bars": 60,
    "min_overlap": 20,
    "cluster_threshold": 0.6,
    "min_cluster_size": 3,
    "min_correlation": 0.6,
    "spread_z": 1.5,
    "resonance_threshold": 0.6,
    "anomaly_window": 20,
    "anomaly_min_corr": 0.7,
    "anomaly_min_delta": 0.4,
    "max_pairs": 40,
}


@dataclass(frozen=True, slots=True)
class ScanOutcome:
    """扫描结果摘要；`status` 直接决定 `opportunity_run.status`。"""

    run: OpportunityRun
    status: str
    reason: str | None
    counts: dict[str, Any]


@dataclass(frozen=True, slots=True)
class UniverseRow:
    instrument_id: int
    inst_id: str
    symbol: str
    asset_class: str | None


def params_from_settings(settings: Settings) -> dict[str, Any]:
    """把配置摊平成可复现的参数快照（写进 `opportunity_run.params`）。"""

    return {
        "bar": settings.opportunity_bar,
        "lookback_bars": settings.opportunity_lookback_bars,
        "min_overlap": settings.opportunity_min_overlap,
        "cluster_threshold": settings.opportunity_cluster_threshold,
        "min_cluster_size": settings.opportunity_min_cluster_size,
        "min_correlation": settings.opportunity_min_correlation,
        "spread_z": settings.opportunity_spread_z,
        "resonance_threshold": settings.opportunity_resonance_threshold,
        "anomaly_window": settings.opportunity_anomaly_window,
        "anomaly_min_corr": settings.opportunity_anomaly_min_corr,
        "anomaly_min_delta": settings.opportunity_anomaly_min_delta,
        "max_pairs": settings.opportunity_max_pairs,
    }


def merge_params(base: Mapping[str, Any], override: Mapping[str, Any] | None) -> dict[str, Any]:
    """只允许覆盖已知参数；未知键直接拒绝，避免「传了但不生效」的静默错误。"""

    merged = dict(base)
    if not override:
        return merged
    unknown = sorted(set(override) - set(DEFAULT_PARAMS))
    if unknown:
        raise ValueError(f"unknown scan params: {', '.join(unknown)}")
    merged.update(override)
    return merged


def compute_run_key(
    as_of: datetime,
    universe: Sequence[str] | None,
    params: Mapping[str, Any],
) -> str:
    payload = {
        "as_of": as_of.isoformat(),
        "universe": sorted(universe) if universe else None,
        "params": dict(params),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _ratio(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(repr(float(value))).quantize(RATIO_QUANT)


async def load_universe(
    session: AsyncSession,
    universe: Sequence[str] | None = None,
) -> list[UniverseRow]:
    """取 `instCategory=3` 的全部标的；`universe` 只做过滤，不做硬编码计数。"""

    rows = await session.execute(
        select(
            Instrument.id,
            Instrument.inst_id,
            Instrument.uly,
            Instrument.asset_class,
        )
        .where(Instrument.inst_category == INST_CATEGORY_US_STOCK)
        .order_by(Instrument.inst_id)
    )
    wanted = {item.upper() for item in universe} if universe else None
    result: list[UniverseRow] = []
    for instrument_id, inst_id, uly, asset_class in rows.all():
        symbol = (uly or inst_id.split("-")[0]).upper()
        if wanted is not None and symbol not in wanted and inst_id.upper() not in wanted:
            continue
        result.append(
            UniverseRow(
                instrument_id=instrument_id,
                inst_id=inst_id,
                symbol=symbol,
                asset_class=asset_class,
            )
        )
    return result


async def resolve_as_of(
    session: AsyncSession,
    instrument_ids: Sequence[int],
    bar: str,
) -> datetime | None:
    """截面时刻 = universe 内已确认 K 线的最新开盘时间。"""

    if not instrument_ids:
        return None
    return await session.scalar(
        select(func.max(Candle.open_time)).where(
            Candle.instrument_id.in_(list(instrument_ids)),
            Candle.bar == bar,
            Candle.confirm.is_(True),
        )
    )


async def load_bars(
    session: AsyncSession,
    instrument_ids: Sequence[int],
    bar: str,
    as_of: datetime,
    lookback_bars: int,
) -> dict[int, list[Bar]]:
    """批量读取截至 `as_of` 的已确认 K 线；每只标的保留最近 `lookback_bars` 根。"""

    if not instrument_ids:
        return {}
    window_start = as_of - timedelta(days=lookback_bars * 2 + 7)
    rows = await session.execute(
        select(
            Candle.instrument_id,
            Candle.open_time,
            Candle.open,
            Candle.high,
            Candle.low,
            Candle.close,
            Candle.vol,
        )
        .where(
            Candle.instrument_id.in_(list(instrument_ids)),
            Candle.bar == bar,
            Candle.confirm.is_(True),
            Candle.open_time >= window_start,
            Candle.open_time <= as_of,
        )
        .order_by(Candle.instrument_id, Candle.open_time)
    )
    grouped: dict[int, list[Bar]] = {}
    for instrument_id, open_time, _open, high, low, close, vol in rows.all():
        grouped.setdefault(instrument_id, []).append(
            Bar(
                open_time=open_time,
                high=float(high),
                low=float(low),
                close=float(close),
                vol=float(vol),
            )
        )
    for instrument_id, series in grouped.items():
        grouped[instrument_id] = series[-lookback_bars:]
    return grouped


def log_return_series(bars: Sequence[Bar]) -> dict[datetime, float]:
    """对数收益率序列（时间戳 → 收益），用于相关矩阵与聚类。"""

    series: dict[datetime, float] = {}
    for previous, current in pairwise(bars):
        if previous.close > 0.0 and current.close > 0.0:
            series[current.open_time] = log(current.close / previous.close)
    return series


def log_level_series(bars: Sequence[Bar]) -> dict[datetime, float]:
    """对数价格序列（时间戳 → 对数收盘价），用于价差 z 值。"""

    return {bar.open_time: log(bar.close) for bar in bars if bar.close > 0.0}


def _snapshot_payload(run_id: int, as_of: datetime, instrument_id: int, section: CrossSection):
    return {
        "as_of": as_of,
        "run_id": run_id,
        "instrument_id": instrument_id,
        "ret_1d": _ratio(section.ret_1d),
        "ret_5d": _ratio(section.ret_5d),
        "ret_20d": _ratio(section.ret_20d),
        "vol_20d": _ratio(section.vol_20d),
        "atr_14": _ratio(section.atr_14),
        "volume_z": _ratio(section.volume_z),
        "high_20d": _ratio(section.high_20d),
        "low_20d": _ratio(section.low_20d),
        "extras": {
            "bars": section.bars,
            "defined": section.defined,
            "window": {
                "vol": features.DEFAULT_VOL_WINDOW,
                "atr": features.DEFAULT_ATR_WINDOW,
                "range": features.DEFAULT_RANGE_WINDOW,
            },
            "atr_method": "simple_mean",
        },
    }


async def _write_snapshots(
    session: AsyncSession,
    run_id: int,
    as_of: datetime,
    sections: Mapping[int, CrossSection],
) -> int:
    if not sections:
        return 0
    stmt = pg_insert(MarketSnapshot).values(
        [
            _snapshot_payload(run_id, as_of, instrument_id, section)
            for instrument_id, section in sorted(sections.items())
        ]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["as_of", "instrument_id"],
        set_={
            "run_id": stmt.excluded.run_id,
            "ret_1d": stmt.excluded.ret_1d,
            "ret_5d": stmt.excluded.ret_5d,
            "ret_20d": stmt.excluded.ret_20d,
            "vol_20d": stmt.excluded.vol_20d,
            "atr_14": stmt.excluded.atr_14,
            "volume_z": stmt.excluded.volume_z,
            "high_20d": stmt.excluded.high_20d,
            "low_20d": stmt.excluded.low_20d,
            "extras": stmt.excluded.extras,
        },
    )
    await session.execute(stmt)
    return len(sections)


def _member_feature(row: UniverseRow, member: Any, section: CrossSection) -> MemberFeature:
    return MemberFeature(
        instrument_id=row.instrument_id,
        inst_id=row.inst_id,
        symbol=row.symbol,
        ret_1d=section.ret_1d,
        ret_5d=section.ret_5d,
        ret_20d=section.ret_20d,
        vol_20d=section.vol_20d,
        distance=member.distance,
        correlation=member.correlation,
    )


def _cluster_label(index: int) -> str:
    return f"cluster-{index + 1:02d}"


def _centroid(sections: Sequence[CrossSection]) -> dict[str, Any]:
    def _mean(values: Sequence[float | None]) -> float | None:
        numbers = [value for value in values if value is not None]
        return sum(numbers) / len(numbers) if numbers else None

    return {
        "ret_1d": _mean([section.ret_1d for section in sections]),
        "ret_5d": _mean([section.ret_5d for section in sections]),
        "vol_20d": _mean([section.vol_20d for section in sections]),
    }


async def _clear_children(session: AsyncSession, run_id: int) -> None:
    cluster_ids = (
        await session.scalars(select(AssetCluster.id).where(AssetCluster.run_id == run_id))
    ).all()
    if cluster_ids:
        await session.execute(
            delete(ClusterMember).where(ClusterMember.cluster_id.in_(list(cluster_ids)))
        )
    await session.execute(delete(AssetCluster).where(AssetCluster.run_id == run_id))
    await session.execute(delete(Opportunity).where(Opportunity.run_id == run_id))


async def scan(
    session: AsyncSession,
    *,
    as_of: datetime | None = None,
    universe: Sequence[str] | None = None,
    params: Mapping[str, Any] | None = None,
    settings: Settings | None = None,
) -> ScanOutcome:
    """执行一次全市场扫描，返回批次与计数；异常由调用方（任务层）标记失败。"""

    current = settings or get_settings()
    effective = merge_params(params_from_settings(current), params)
    started = time.perf_counter()

    universe_rows = await load_universe(session, universe)
    instrument_ids = [row.instrument_id for row in universe_rows]
    resolved_as_of = as_of or await resolve_as_of(session, instrument_ids, str(effective["bar"]))
    if resolved_as_of is None:
        raise LookupError("no confirmed candles available for the selected universe")

    run_key = compute_run_key(resolved_as_of, universe, effective)
    inserted = (
        await session.execute(
            pg_insert(OpportunityRun)
            .values(
                run_key=run_key,
                as_of=resolved_as_of,
                universe_size=len(universe_rows),
                params=effective,
                status=STATUS_RUNNING,
                counts={},
            )
            .on_conflict_do_nothing(index_elements=["run_key"])
            .returning(OpportunityRun.id)
        )
    ).scalar_one_or_none()
    if inserted is None:
        run = await session.scalar(select(OpportunityRun).where(OpportunityRun.run_key == run_key))
        if run is None:  # pragma: no cover - 唯一键冲突后必然能查到
            raise LookupError(f"opportunity run vanished: {run_key}")
        await _clear_children(session, run.id)
        run.status = STATUS_RUNNING
        run.universe_size = len(universe_rows)
        run.params = effective
        run.counts = {}
        run.error = None
    else:
        run = await session.scalar(select(OpportunityRun).where(OpportunityRun.id == inserted))
        if run is None:  # pragma: no cover
            raise LookupError(f"opportunity run vanished: {inserted}")
    await session.commit()

    bars_by_instrument = await load_bars(
        session,
        instrument_ids,
        str(effective["bar"]),
        resolved_as_of,
        int(effective["lookback_bars"]),
    )

    missing_private: list[str] = []
    missing_candles: list[str] = []
    insufficient: list[str] = []
    sections: dict[int, CrossSection] = {}
    returns_by_instrument: dict[int, dict[datetime, float]] = {}
    levels_by_instrument: dict[int, dict[datetime, float]] = {}
    rows_by_instrument = {row.instrument_id: row for row in universe_rows}
    min_overlap = int(effective["min_overlap"])

    for row in universe_rows:
        series = bars_by_instrument.get(row.instrument_id, [])
        if not series:
            if row.symbol in PRIVATE_COMPANIES:
                missing_private.append(row.symbol)
            else:
                missing_candles.append(row.symbol)
            continue
        sections[row.instrument_id] = features.cross_section(series)
        if len(series) >= min_overlap + 1:
            returns_by_instrument[row.instrument_id] = log_return_series(series)
            levels_by_instrument[row.instrument_id] = log_level_series(series)
        else:
            insufficient.append(row.symbol)

    snapshot_count = await _write_snapshots(session, run.id, resolved_as_of, sections)

    clustering = cluster(
        returns_by_instrument,
        threshold=float(effective["cluster_threshold"]),
        min_overlap=min_overlap,
        min_size=int(effective["min_cluster_size"]),
    )

    cluster_inputs: list[tuple[str, list[MemberFeature], float | None]] = []
    for index, grouped in enumerate(clustering.clusters):
        label = _cluster_label(index)
        section_list: list[CrossSection] = []
        cluster_row = AssetCluster(
            run_id=run.id,
            label=label,
            method="hierarchical",
            silhouette=_ratio(grouped.silhouette),
            size=grouped.size,
            centroid={},
        )
        session.add(cluster_row)
        await session.flush()
        members: list[MemberFeature] = []
        for member in grouped.members:
            row = rows_by_instrument.get(member.key)
            section = sections.get(member.key)
            if row is None or section is None:  # pragma: no cover - 聚类输入即来自 universe
                continue
            section_list.append(section)
            members.append(_member_feature(row, member, section))
            session.add(
                ClusterMember(
                    cluster_id=cluster_row.id,
                    instrument_id=member.key,
                    distance=_ratio(member.distance),
                    weight=_ratio(member.correlation),
                )
            )
        cluster_row.centroid = _centroid(section_list)
        cluster_inputs.append((label, members, grouped.silhouette))

    directional = directional_candidates(
        cluster_inputs,
        strength_threshold=float(effective["resonance_threshold"]),
    )
    pairs = pair_candidates(
        cluster_inputs,
        levels_by_instrument,
        min_correlation=float(effective["min_correlation"]),
        z_threshold=float(effective["spread_z"]),
        min_overlap=int(effective["min_overlap"]),
        anomaly_window=int(effective["anomaly_window"]),
        anomaly_min_abs=float(effective["anomaly_min_corr"]),
        anomaly_min_delta=float(effective["anomaly_min_delta"]),
        max_pairs=int(effective["max_pairs"]),
    )

    candidates: list[Candidate] = [*directional, *pairs]
    if candidates:
        await session.execute(
            pg_insert(Opportunity)
            .values(
                [
                    {
                        "run_id": run.id,
                        "kind": candidate.kind,
                        "primary_instrument_id": candidate.primary_instrument_id,
                        "direction": candidate.direction,
                        "score": _ratio(candidate.score),
                        "horizon": candidate.horizon,
                        "reasons": list(candidate.reasons),
                        "evidence": candidate.evidence,
                        "dedupe_key": candidate.dedupe_key,
                    }
                    for candidate in candidates
                ]
            )
            .on_conflict_do_nothing(index_elements=["run_id", "dedupe_key"])
        )

    all_returns = [section.ret_1d for section in sections.values() if section.ret_1d is not None]
    counts: dict[str, Any] = {
        "universe": len(universe_rows),
        "snapshot": snapshot_count,
        "missing": {
            "private_company": sorted(missing_private),
            "no_candles": sorted(missing_candles),
            "insufficient_bars": sorted(insufficient),
        },
        "analysed": len(returns_by_instrument),
        "clusters": len(clustering.clusters),
        "undefined_pairs": clustering.undefined_pairs,
        "opportunities": {
            "directional": len(directional),
            "relative_value": len(pairs),
            "total": len(candidates),
        },
        "breadth": market_breadth(all_returns),
        "as_of": resolved_as_of.isoformat(),
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "bar": effective["bar"],
        "lookback_bars": effective["lookback_bars"],
    }
    # `ok` 只表示「该分析的都分析了」：私募公司天然没有行情，按设计排除；
    # 有行情却进不了聚类的（无 K 线 = 还没回填，样本不足 = 历史太短）属于数据
    # 未就绪，必须降级为 `partial`，否则调用方无法区分完整分析与半成品分析。
    degraded = len(missing_candles) + len(insufficient)
    status = STATUS_PARTIAL if degraded else STATUS_OK
    run.status = status
    run.counts = counts
    run.finished_at = datetime.now(UTC)
    run.universe_size = len(universe_rows)
    await session.commit()
    await session.refresh(run)
    return ScanOutcome(run=run, status=status, reason=None, counts=counts)


__all__ = [
    "DEFAULT_PARAMS",
    "INST_CATEGORY_US_STOCK",
    "STATUS_FAILED",
    "STATUS_OK",
    "STATUS_PARTIAL",
    "STATUS_RUNNING",
    "STATUS_SKIPPED",
    "ScanOutcome",
    "UniverseRow",
    "compute_run_key",
    "load_bars",
    "load_universe",
    "log_level_series",
    "log_return_series",
    "merge_params",
    "params_from_settings",
    "resolve_as_of",
    "scan",
]

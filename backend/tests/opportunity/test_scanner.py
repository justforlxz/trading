"""全市场扫描编排单测（P1-11）：覆盖率、幂等与「无法计算的原因必须留痕」。"""

import math
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.market.models import Instrument
from app.opportunity import scanner
from app.opportunity.models import AssetCluster, ClusterMember, Opportunity, OpportunityRun
from app.research.models import MarketSnapshot
from tests.market.support import insert_instrument
from tests.research.support import seed_okx_series

START = datetime(2026, 9, 1, tzinfo=UTC)
DAYS = 60


def _scan_settings() -> Settings:
    return Settings(
        opportunity_lookback_bars=DAYS,
        opportunity_min_overlap=20,
        opportunity_cluster_threshold=0.6,
        opportunity_min_cluster_size=3,
        opportunity_min_correlation=0.6,
        opportunity_resonance_threshold=0.6,
        opportunity_spread_z=1.5,
        opportunity_anomaly_window=20,
        opportunity_max_pairs=10,
    )


def _rising(offset: float, scale: float = 1.0) -> list[float]:
    return [
        offset + 0.5 * index * scale + 6.0 * math.sin(0.4 * index) * scale for index in range(DAYS)
    ]


def _falling(offset: float, scale: float = 1.0) -> list[float]:
    return [
        offset - 0.5 * index * scale - 6.0 * math.sin(0.4 * index) * scale for index in range(DAYS)
    ]


async def _seed_two_groups(session) -> dict[str, int]:
    series = {
        "UP1-USDT-SWAP": _rising(100.0),
        "UP2-USDT-SWAP": _rising(100.0, 1.02),
        "UP3-USDT-SWAP": _rising(100.0, 0.98),
        "DN1-USDT-SWAP": _falling(240.0),
        "DN2-USDT-SWAP": _falling(240.0, 1.02),
        "DN3-USDT-SWAP": _falling(240.0, 0.98),
    }
    # 保证最后一根同向：上涨组收高、下跌组收低，让共振方向明确。
    for key in ("UP1-USDT-SWAP", "UP2-USDT-SWAP", "UP3-USDT-SWAP"):
        series[key][-1] = series[key][-2] * 1.02
    for key in ("DN1-USDT-SWAP", "DN2-USDT-SWAP", "DN3-USDT-SWAP"):
        series[key][-1] = series[key][-2] * 0.98
    return await seed_okx_series(session, series, bar="1d", start=START)


async def test_scan_writes_snapshot_clusters_and_explainable_opportunities(session) -> None:
    await _seed_two_groups(session)

    outcome = await scanner.scan(session, settings=_scan_settings())

    assert outcome.status == "ok"
    assert outcome.run.universe_size == 6
    assert outcome.counts["snapshot"] == 6
    assert outcome.counts["universe"] == 6
    assert outcome.counts["clusters"] == 2
    snapshot_rows = await session.scalar(
        select(func.count())
        .select_from(MarketSnapshot)
        .where(MarketSnapshot.as_of == outcome.run.as_of)
    )
    assert snapshot_rows == 6

    cluster_count = await session.scalar(
        select(func.count()).select_from(AssetCluster).where(AssetCluster.run_id == outcome.run.id)
    )
    assert cluster_count == 2
    member_total = await session.scalar(
        select(func.count())
        .select_from(ClusterMember)
        .join(AssetCluster, AssetCluster.id == ClusterMember.cluster_id)
        .where(AssetCluster.run_id == outcome.run.id)
    )
    assert member_total == 6

    opportunities = (
        await session.scalars(select(Opportunity).where(Opportunity.run_id == outcome.run.id))
    ).all()
    assert opportunities, "扫描必须产出至少一条机会"
    for opportunity in opportunities:
        assert opportunity.reasons
        assert any(
            isinstance(value, int | float) and not isinstance(value, bool)
            for value in opportunity.evidence.values()
        )
        assert opportunity.score > 0

    directional = [item for item in opportunities if item.kind == "directional"]
    assert directional
    assert {item.direction for item in directional} == {"long", "short"}


async def test_rerun_with_same_key_updates_the_same_batch(session) -> None:
    await _seed_two_groups(session)

    first = await scanner.scan(session, settings=_scan_settings())
    second = await scanner.scan(session, settings=_scan_settings())

    total_runs = await session.scalar(select(func.count()).select_from(OpportunityRun))
    assert total_runs == 1
    assert first.run.id == second.run.id
    assert first.run.run_key == second.run.run_key

    # 重跑不应把子表堆成双份。
    clusters = await session.scalar(
        select(func.count()).select_from(AssetCluster).where(AssetCluster.run_id == first.run.id)
    )
    assert clusters == 2
    opportunity_rows = await session.scalar(
        select(func.count()).select_from(Opportunity).where(Opportunity.run_id == first.run.id)
    )
    assert opportunity_rows == first.counts["opportunities"]["total"]


async def test_private_company_without_candles_is_reported_not_faked(session) -> None:
    await _seed_two_groups(session)
    await insert_instrument(session, "OPENAI-USDT-SWAP", asset_class="private_company")

    outcome = await scanner.scan(session, settings=_scan_settings())

    assert outcome.run.universe_size == 7
    assert outcome.counts["snapshot"] == 6
    assert outcome.counts["missing"]["private_company"] == ["OPENAI"]
    # 私募公司按设计没有行情，不算数据未就绪，批次仍是完整分析。
    assert outcome.status == "ok"
    openai = await session.scalar(
        select(Instrument).where(Instrument.inst_id == "OPENAI-USDT-SWAP")
    )
    assert openai is not None
    snapshot_for_openai = await session.scalar(
        select(func.count())
        .select_from(MarketSnapshot)
        .where(
            MarketSnapshot.as_of == outcome.run.as_of,
            MarketSnapshot.instrument_id == openai.id,
        )
    )
    assert snapshot_for_openai == 0


async def test_scan_without_candles_raises_instead_of_writing_an_empty_batch(session) -> None:
    await insert_instrument(session, "AAPL-USDT-SWAP")

    with pytest.raises(LookupError):
        await scanner.scan(session, settings=_scan_settings())


async def test_unknown_scan_params_are_rejected(session) -> None:
    with pytest.raises(ValueError, match="unknown scan params"):
        scanner.merge_params({"bar": "1d"}, {"nope": 1})


async def test_run_key_is_stable_for_same_inputs() -> None:
    moment = START + timedelta(days=5)
    first = scanner.compute_run_key(moment, ["A", "B"], {"bar": "1d"})
    second = scanner.compute_run_key(moment, ["B", "A"], {"bar": "1d"})
    assert first == second
    assert first != scanner.compute_run_key(moment, None, {"bar": "1d"})


async def test_partial_status_when_a_symbol_cannot_join_the_analysis(session) -> None:
    """有 K 线但样本不足的标的必须把批次降级为 `partial`。

    回归阻断问题：此前状态判定用 `snapshot + 缺失` 覆盖 universe，恒等于
    `ok`，`insufficient_bars` 记录了却不影响状态。
    """

    await _seed_two_groups(session)
    # 5 根日线：能进特征截面，但达不到 min_overlap（20），进不了聚类。
    await seed_okx_series(session, {"THIN-USDT-SWAP": _rising(100.0)[:5]}, bar="1d", start=START)

    outcome = await scanner.scan(session, settings=_scan_settings())

    assert outcome.status == "partial"
    assert outcome.run.status == "partial"
    assert outcome.counts["missing"]["insufficient_bars"] == ["THIN"]
    assert outcome.counts["missing"]["no_candles"] == []
    assert outcome.counts["universe"] == 7
    assert outcome.counts["snapshot"] == 7
    assert outcome.counts["analysed"] == 6


async def test_partial_status_when_symbols_have_no_candles_yet(session) -> None:
    """未回填的标的同样意味着数据未就绪，批次不能标记为 `ok`。"""

    await _seed_two_groups(session)
    await insert_instrument(session, "EMPTY-USDT-SWAP")

    outcome = await scanner.scan(session, settings=_scan_settings())

    assert outcome.status == "partial"
    assert outcome.counts["missing"]["no_candles"] == ["EMPTY"]
    assert outcome.counts["analysed"] == 6

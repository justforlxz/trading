"""P4 助手测试夹具：库准备、表清理、AI 配置注入与数据播种。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.market.conftest import MARKET_TABLES, _database_url
from tests.risk.conftest import (
    RISK_TABLES,
    Seeded,
    _instrument,
    _prepare_database_blocking,
    seed_strategy,
)

# 关系/机会表不在 market/risk 的清理清单里, 必须一起清, 否则唯一键会跨用例冲突。
AI_TABLES = (
    "research.relation_edge",
    "research.relation_snapshot",
    "research.relative_strength_snapshot",
    "research.market_snapshot",
    "research.target_symbol",
    "opportunity.cluster_member",
    "opportunity.asset_cluster",
    "opportunity.opportunity",
    "opportunity.opportunity_run",
)

TRUNCATE_SQL = (
    f"TRUNCATE {', '.join((*AI_TABLES, *RISK_TABLES, *MARKET_TABLES))} RESTART IDENTITY CASCADE"
)


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _database_url()
    if not url:
        pytest.skip("未配置 TEST_DATABASE_URL / DATABASE_URL: 跳过数据库用例")
    _prepare_database_blocking(url)
    return url


@pytest_asyncio.fixture(autouse=True)
async def clean_database(database_url: str) -> None:
    from app.db import session as db_session

    async with db_session.session_factory() as db:
        await db.execute(text(TRUNCATE_SQL))
        await db.commit()


@pytest_asyncio.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    from app.db import session as db_session

    async with db_session.session_factory() as db:
        yield db


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as api:
        yield api


@dataclass(slots=True)
class AiSettings:
    """测试内可改写的助手配置（默认规则式, 不触网）。"""

    enabled: bool = True
    provider: str = "rule_based"
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    fallback_enabled: bool = True
    max_citations: int = 20


@pytest.fixture
def configure_ai(monkeypatch: pytest.MonkeyPatch):
    """把 `app.ai.service` 的配置替换成测试值。"""

    from app.ai import service as ai_service
    from app.config import Settings

    def configure(**overrides: Any) -> AiSettings:
        values = AiSettings(**overrides)
        settings = Settings(
            ai_enabled=values.enabled,
            ai_provider=values.provider,
            ai_model=values.model,
            ai_base_url=values.base_url,
            ai_api_key=values.api_key,
            ai_fallback_enabled=values.fallback_enabled,
            ai_max_citations=values.max_citations,
        )
        monkeypatch.setattr(ai_service, "get_settings", lambda: settings)
        return values

    return configure


@dataclass(slots=True)
class FakeLlm:
    """假适配器：记录提示词, 返回测试规定的文本, 不访问网络。"""

    reply: str = "基于事实的回答"
    calls: list[dict[str, str]] = field(default_factory=list)

    async def complete(self, *, system: str, prompt: str):
        from app.ai.adapter import LlmResult

        self.calls.append({"system": system, "prompt": prompt})
        return LlmResult(text=self.reply, provider="fake", model="fake-model", tokens=42)


@pytest.fixture
def use_fake_llm(monkeypatch: pytest.MonkeyPatch):
    """把 openai 适配器替换成假实现；配合 `configure_ai(provider="openai", ...)`。"""

    from app.ai import service as ai_service

    def install(reply: str = "基于事实的回答") -> FakeLlm:
        fake = FakeLlm(reply=reply)
        monkeypatch.setattr(ai_service, "build_adapter", lambda config: fake)
        return fake

    return install


@dataclass(slots=True)
class TargetSeed:
    target_id: int
    instrument_id: int
    inst_id: str


async def seed_target(
    session: AsyncSession,
    *,
    symbol: str = "AAPL",
    inst_id: str | None = None,
    enabled: bool = True,
) -> TargetSeed:
    """建一只目标股票与对应 instrument（不建 K 线）。"""

    from app.research.models import TargetSymbol

    resolved = inst_id or f"{symbol}-USDT-SWAP"
    instrument_id = await _instrument(session, resolved)
    target = TargetSymbol(
        symbol=symbol,
        exchange="NASDAQ",
        display_name=symbol,
        instrument_id=instrument_id,
        enabled=enabled,
        note=None,
    )
    session.add(target)
    await session.flush()
    await session.commit()
    return TargetSeed(target_id=target.id, instrument_id=instrument_id, inst_id=resolved)


async def seed_relations(
    session: AsyncSession,
    *,
    target_id: int,
    edges: tuple[tuple[str, str, int], ...] = (
        ("MSFT", "0.8123456789", 0),
        ("NVDA", "-0.7345678901", 1),
    ),
) -> int:
    """建一份关系快照与显著边, 返回 snapshot_id。"""

    from app.research.models import RelationEdge, RelationSnapshot

    moment = datetime.now(UTC).replace(microsecond=0)
    snapshot = RelationSnapshot(
        target_id=target_id,
        as_of=moment,
        window_bars=200,
        method="pearson",
        price_basis="close",
        lag_max=3,
        sample_size=180,
        run_key=f"ai-test-{target_id}-{moment.timestamp()}",
        params={},
    )
    session.add(snapshot)
    await session.flush()
    for rank, (symbol, coefficient, best_lag) in enumerate(edges):
        counterparty_id = await _instrument(session, f"{symbol}-USDT-SWAP")
        session.add(
            RelationEdge(
                snapshot_id=snapshot.id,
                counterparty_id=counterparty_id,
                coefficient=Decimal(coefficient),
                best_lag=best_lag,
                p_value=Decimal("0.01"),
                stability=Decimal("0.9"),
                rank=rank,
            )
        )
    await session.commit()
    return snapshot.id


METRIC_UNITS = {
    "annualized_return": "ratio",
    "cost_ratio": "ratio",
    "max_drawdown": "ratio",
    "profit_loss_ratio": "ratio",
    "sharpe": "ratio",
    "sortino": "ratio",
    "total_return": "ratio",
    "trade_count": "count",
    "turnover": "ratio",
    "win_rate": "ratio",
}

DEFAULT_METRICS = {
    "annualized_return": "-0.4022330000",
    "cost_ratio": "0.0012100000",
    "max_drawdown": "0.3812000000",
    "profit_loss_ratio": "0.8123000000",
    "sharpe": "-1.8181257148",
    "sortino": "-2.1133000000",
    "total_return": "-0.3236520556",
    "trade_count": "24.0000000000",
    "turnover": "1.4321000000",
    "win_rate": "0.3750000000",
}


async def seed_metrics(
    session: AsyncSession,
    *,
    run_id: int,
    values: dict[str, str] | None = None,
) -> None:
    from app.backtest.models import BacktestMetric

    for name, value in (values or DEFAULT_METRICS).items():
        session.add(
            BacktestMetric(
                run_id=run_id,
                name=name,
                value=Decimal(value),
                unit=METRIC_UNITS[name],
            )
        )
    await session.commit()


async def seed_approval(session: AsyncSession, *, strategy_id: int) -> None:
    from app.strategy.models import StrategyApproval

    session.add(
        StrategyApproval(
            strategy_id=strategy_id,
            decision="approved",
            content_hash="0" * 64,
            reviewer="tester",
        )
    )
    await session.commit()


async def seed_opportunity(
    session: AsyncSession,
    *,
    instrument_id: int,
    direction: str = "long",
) -> int:
    """建一条机会与批次头, 返回 opportunity_id。"""

    from app.opportunity.models import Opportunity, OpportunityRun

    moment = datetime.now(UTC)
    run = OpportunityRun(
        run_key=f"ai-test-run-{moment.timestamp()}",
        as_of=moment,
        universe_size=1,
        params={},
        status="ok",
    )
    session.add(run)
    await session.flush()
    opportunity = Opportunity(
        run_id=run.id,
        kind="resonance",
        primary_instrument_id=instrument_id,
        direction=direction,
        score=Decimal("0.88"),
        horizon="swing",
        reasons=["测试机会: 群体共振"],
        evidence={},
        dedupe_key=f"ai-test-{instrument_id}",
    )
    session.add(opportunity)
    await session.commit()
    return opportunity.id


async def seed_full_backtest(
    session: AsyncSession,
    *,
    values: dict[str, str] | None = None,
) -> Seeded:
    """策略 + 腿 + 成功回测 + 10 项指标 + 审批记录。"""

    seeded = await seed_strategy(session)
    assert seeded.run_id is not None
    await seed_metrics(session, run_id=seeded.run_id, values=values)
    await seed_approval(session, strategy_id=seeded.strategy_id)
    return seeded


__all__ = [
    "AI_TABLES",
    "DEFAULT_METRICS",
    "AiSettings",
    "FakeLlm",
    "TargetSeed",
    "clean_database",
    "client",
    "configure_ai",
    "database_url",
    "seed_approval",
    "seed_full_backtest",
    "seed_metrics",
    "seed_opportunity",
    "seed_relations",
    "seed_strategy",
    "seed_target",
    "session",
    "use_fake_llm",
]

"""风控测试夹具：库准备、表清理、可注入投递与策略/回测/行情播种。"""

import subprocess
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.market.conftest import MARKET_TABLES, _database_url

BACKEND_DIR = Path(__file__).resolve().parents[2]
RISK_TABLES = (
    "risk.risk_event",
    "risk.risk_policy",
    "ops.job_run",
    "ops.audit_log",
    "backtest.backtest_trade",
    "backtest.backtest_equity_point",
    "backtest.backtest_metric",
    "backtest.backtest_run",
    "strategy.strategy_transition",
    "strategy.strategy_approval",
    "strategy.strategy_leg",
    "strategy.strategy",
)

TRUNCATE_SQL = f"TRUNCATE {', '.join((*RISK_TABLES, *MARKET_TABLES))} RESTART IDENTITY CASCADE"

# 子进程完成建库 + 迁移：不碰当前进程的事件循环，避免影响后续目录的 async 用例。
PREPARE_SNIPPET = """
import asyncio
import os
import subprocess
import sys

import asyncpg

url = sys.argv[1]
backend_dir = sys.argv[2]
dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
base, _, name = dsn.rpartition("/")
name = name.split("?", 1)[0]


async def create() -> None:
    connection = await asyncpg.connect(f"{base}/postgres")
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", name
        )
        if not exists:
            await connection.execute(f'CREATE DATABASE "{name}"')
    finally:
        await connection.close()


asyncio.run(create())
subprocess.run(
    [sys.executable, "-m", "alembic", "upgrade", "head"],
    cwd=backend_dir,
    env={**os.environ, "DATABASE_URL": url},
    check=True,
)
"""


def _prepare_database_blocking(url: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", PREPARE_SNIPPET, url, str(BACKEND_DIR)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:  # pragma: no cover - 环境故障
        raise RuntimeError(f"prepare test database failed: {result.stderr}")


@pytest.fixture(scope="session")
def database_url() -> str:
    """测试库 URL；建库与迁移在子进程完成。"""

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
def dispatched() -> list[dict[str, Any]]:
    """记录被投递的任务参数；测试自己决定何时同步执行。"""

    return []


@pytest.fixture
async def client(
    dispatched: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    """不连 Redis 的 API 客户端：`dispatch` 只记录，不真的入队。"""

    from app.api.v1 import risk as risk_api
    from app.main import create_app

    app = create_app()

    async def fake_dispatch(task_name: str, **kwargs: object) -> str | None:
        dispatched.append({"task_name": task_name, **kwargs})
        return "test-arq-job"

    monkeypatch.setattr(risk_api, "dispatch", fake_dispatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as api:
        yield api


DEFAULT_CAPITAL = Decimal("100000")
DEFAULT_LEGS = (
    ("BTC-USDT-SWAP", "long", Decimal("0.6")),
    ("ETH-USDT-SWAP", "short", Decimal("0.4")),
)


@dataclass(slots=True)
class Seeded:
    """播种结果，供测试直接引用主键。"""

    strategy_id: int
    run_id: int | None
    instrument_ids: dict[str, int]


async def _instrument(session: AsyncSession, inst_id: str) -> int:
    from app.market.models import Instrument

    existing = (
        await session.execute(select(Instrument).where(Instrument.inst_id == inst_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id
    instrument = Instrument(
        inst_id=inst_id,
        inst_family=inst_id.split("-")[0],
        uly=inst_id.split("-")[0],
        inst_category=1,
        asset_class="us_stock",
        ct_val=Decimal("1"),
        ct_val_ccy=inst_id.split("-")[1],
        lot_sz=Decimal("1"),
        min_sz=Decimal("1"),
        tick_sz=Decimal("0.01"),
        lever=Decimal("10"),
        state="live",
        rule_type="normal",
        raw={},
    )
    session.add(instrument)
    await session.flush()
    return instrument.id


async def seed_strategy(
    session: AsyncSession,
    *,
    status: str = "approved",
    legs: tuple[tuple[str, str, Decimal], ...] = DEFAULT_LEGS,
    capital: Decimal = DEFAULT_CAPITAL,
    equity: tuple[Decimal, ...] | None = None,
    candles: bool = True,
    backtest: bool = True,
    strategy_key: str = "risk-test-strategy",
    bar: str = "1d",
) -> Seeded:
    """播种一只策略及其腿、确认 K 线与成功回测净值。"""

    from app.backtest.models import BacktestEquityPoint, BacktestRun
    from app.market.models import Candle
    from app.strategy.models import Strategy, StrategyLeg

    instrument_ids: dict[str, int] = {}
    for inst_id, _side, _weight in legs:
        instrument_ids[inst_id] = await _instrument(session, inst_id)

    moment = datetime.now(UTC)
    strategy = Strategy(
        strategy_key=strategy_key,
        name=strategy_key,
        kind="directional",
        status=status,
        templates=[],
        params={},
        content_hash="0" * 64,
        version=1,
    )
    session.add(strategy)
    await session.flush()

    for rank, (inst_id, side, weight) in enumerate(legs):
        session.add(
            StrategyLeg(
                strategy_id=strategy.id,
                instrument_id=instrument_ids[inst_id],
                side=side,
                target_weight=weight,
                rationale="test",
                rank=rank,
            )
        )

    if candles:
        for instrument_id in instrument_ids.values():
            session.add(
                Candle(
                    instrument_id=instrument_id,
                    bar=bar,
                    open_time=moment - timedelta(hours=1),
                    open=Decimal("100"),
                    high=Decimal("101"),
                    low=Decimal("99"),
                    close=Decimal("100"),
                    vol=Decimal("1"),
                    vol_ccy=Decimal("1"),
                    vol_ccy_quote=Decimal("100"),
                    confirm=True,
                    source="test",
                )
            )

    run_id: int | None = None
    if backtest:
        run = BacktestRun(
            run_key=f"{strategy_key}-run",
            strategy_id=strategy.id,
            strategy_version=1,
            window_start=moment - timedelta(days=30),
            window_end=moment,
            bar=bar,
            initial_capital=capital,
            cost_model={},
            params={},
            status="ok",
        )
        session.add(run)
        await session.flush()
        run_id = run.id
        points = equity if equity is not None else (capital, capital * Decimal("0.8"))
        peak = max(points) if points else capital
        for index, value in enumerate(points):
            drawdown = (peak - value) / peak if peak > 0 else Decimal("0")
            session.add(
                BacktestEquityPoint(
                    run_id=run.id,
                    ts=moment - timedelta(days=len(points) - index),
                    equity=value,
                    cash=value,
                    exposure=Decimal("0"),
                    drawdown=drawdown,
                )
            )

    await session.commit()
    return Seeded(strategy_id=strategy.id, run_id=run_id, instrument_ids=instrument_ids)

"""迁移门禁：0006 是 head、四张表与四个唯一键齐备、升级可重复执行（AC1）。"""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[2]

TABLES = [
    "backtest_equity_point",
    "backtest_metric",
    "backtest_run",
    "backtest_trade",
]
UNIQUE_KEYS = {
    "uq_backtest_run_key",
    "uq_backtest_metric_name",
    "uq_backtest_equity_point_ts",
    "uq_backtest_trade_key",
}


async def test_head_is_0006_and_schema_is_complete(session) -> None:
    head = await session.scalar(text("SELECT version_num FROM alembic_version"))
    assert head == "0006_backtest_schema"

    names = list(
        await session.scalars(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'backtest' ORDER BY table_name"
            )
        )
    )
    assert names == TABLES

    keys = set(
        await session.scalars(
            text(
                "SELECT c.conname FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname = 'backtest' AND c.contype = 'u'"
            )
        )
    )
    assert keys >= UNIQUE_KEYS

    capital = (
        await session.execute(
            text(
                "SELECT numeric_precision, numeric_scale FROM information_schema.columns "
                "WHERE table_schema = 'backtest' AND table_name = 'backtest_run' "
                "AND column_name = 'initial_capital'"
            )
        )
    ).one()
    assert tuple(capital) == (24, 10)


async def test_upgrade_head_is_idempotent(session, database_url: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": database_url},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    head = await session.scalar(text("SELECT version_num FROM alembic_version"))
    assert head == "0006_backtest_schema"

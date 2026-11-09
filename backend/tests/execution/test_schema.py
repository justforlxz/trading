"""execution schema 迁移：版本、表、唯一约束、数值精度与幂等。"""

import os
import subprocess
import sys

from sqlalchemy import text

from tests.execution.conftest import BACKEND_DIR

EXPECTED_TABLES = {"order", "fill", "position", "reconcile_diff"}


async def test_revision_is_execution_schema(session) -> None:
    # head 随阶段推进：P4 新增 0009_mcp_schema，execution 表仍在同一迁移链上。
    version = await session.scalar(text("SELECT version_num FROM alembic_version"))
    assert version == "0009_mcp_schema"


async def test_tables_and_checks(session) -> None:
    rows = await session.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'execution'")
    )
    assert {row[0] for row in rows} == EXPECTED_TABLES

    constraints = {
        row[0]
        for row in await session.execute(
            text("SELECT conname FROM pg_constraint WHERE connamespace = 'execution'::regnamespace")
        )
    }
    assert {
        "uq_execution_order_client_id",
        "uq_execution_fill_key",
        "uq_execution_position_key",
        "ck_execution_order_state",
        "ck_execution_position_side",
    } <= constraints

    index = await session.scalar(
        text(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'execution'"
            " AND indexname = 'uq_execution_reconcile_open'"
        )
    )
    assert index == "uq_execution_reconcile_open"


async def test_money_columns_are_numeric_24_10(session) -> None:
    rows = await session.execute(
        text(
            "SELECT numeric_precision, numeric_scale FROM information_schema.columns"
            " WHERE table_schema = 'execution' AND table_name = 'position'"
            " AND column_name IN ('quantity', 'average_price', 'realized_pnl')"
        )
    )
    assert [tuple(row) for row in rows] == [(24, 10)] * 3


def test_upgrade_head_is_idempotent(database_url: str) -> None:
    """迁移已到 head 时再次执行必须成功（no-op），否则容器启动会反复失败。"""

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

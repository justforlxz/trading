"""MCP 迁移（0009）：schema、表、索引与「已到 head 时再跑是 no-op」。"""

import os
import subprocess
import sys

from sqlalchemy import text

from tests.market.conftest import _database_url
from tests.risk.conftest import BACKEND_DIR

EXPECTED_MCP_TABLES = {"mcp_clients", "mcp_call_log"}


async def test_head_is_0009_mcp_schema(session) -> None:
    version = await session.scalar(text("SELECT version_num FROM alembic_version"))
    assert version == "0009_mcp_schema"


async def test_mcp_tables_and_columns(session) -> None:
    rows = await session.execute(
        text(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = 'mcp' ORDER BY table_name"
        )
    )
    assert {row[0] for row in rows} == EXPECTED_MCP_TABLES

    client_columns = {
        row[0]
        for row in await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_schema = 'mcp' AND table_name = 'mcp_clients'"
            )
        )
    }
    assert {
        "id",
        "name",
        "token_hash",
        "scopes",
        "created_at",
        "last_used_at",
        "revoked_at",
    } <= client_columns

    log_columns = {
        row[0]
        for row in await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_schema = 'mcp' AND table_name = 'mcp_call_log'"
            )
        )
    }
    assert {
        "id",
        "client_id",
        "tool",
        "args_digest",
        "status",
        "error_code",
        "reason",
        "latency_ms",
        "created_at",
    } <= log_columns


async def test_token_hash_is_unique(session) -> None:
    index = await session.scalar(
        text(
            "SELECT indexname FROM pg_indexes"
            " WHERE schemaname = 'mcp' AND indexname = 'uq_mcp_clients_token_hash'"
        )
    )
    assert index == "uq_mcp_clients_token_hash"

    call_log_indexes = {
        row[0]
        for row in await session.execute(
            text(
                "SELECT indexname FROM pg_indexes"
                " WHERE schemaname = 'mcp' AND tablename = 'mcp_call_log'"
            )
        )
    }
    assert {"ix_mcp_call_log_created_at", "ix_mcp_call_log_client"} <= call_log_indexes


async def test_strategy_has_paused_at_column(session) -> None:
    row = await session.scalar(
        text(
            "SELECT is_nullable FROM information_schema.columns"
            " WHERE table_schema = 'strategy' AND table_name = 'strategy'"
            " AND column_name = 'paused_at'"
        )
    )
    assert row == "YES"


def test_upgrade_head_is_idempotent() -> None:
    """迁移已到 head 时再次执行必须成功（no-op），否则容器启动会反复失败。"""

    url = _database_url()
    assert url is not None
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

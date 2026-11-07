"""风控 schema 用例：迁移落点、表结构与迁移幂等。"""

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_migration_head_is_current(session) -> None:
    # head 随阶段推进：P3 新增 0008_execution_schema，风控表仍在同一迁移链上。
    row = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    assert row == "0008_execution_schema"


@pytest.mark.asyncio
async def test_risk_tables_exist(session) -> None:
    rows = (
        await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'risk' ORDER BY table_name"
            )
        )
    ).scalars()
    assert set(rows) == {"risk_event", "risk_policy"}


@pytest.mark.asyncio
async def test_risk_unique_constraints(session) -> None:
    rows = (
        await session.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conname IN ('uq_risk_policy_version', 'uq_risk_event_key')"
            )
        )
    ).scalars()
    assert set(rows) == {"uq_risk_policy_version", "uq_risk_event_key"}


@pytest.mark.asyncio
async def test_risk_decimal_precision(session) -> None:
    rows = (
        await session.execute(
            text(
                "SELECT table_name, column_name, numeric_precision, numeric_scale "
                "FROM information_schema.columns "
                "WHERE table_schema = 'risk' AND column_name IN "
                "('max_order_notional', 'max_leg_weight', 'observed_value')"
            )
        )
    ).all()
    precision = {
        (row.table_name, row.column_name): (row.numeric_precision, row.numeric_scale)
        for row in rows
    }
    assert precision[("risk_policy", "max_order_notional")] == (24, 10)
    assert precision[("risk_policy", "max_leg_weight")] == (12, 10)
    assert precision[("risk_event", "observed_value")] == (24, 10)

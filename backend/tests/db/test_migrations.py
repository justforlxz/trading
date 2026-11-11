"""迁移链与模型的一致性：正向建出全部表、反向删干净、重复执行无副作用。

每个用例都在根 `conftest.py` 给的独立临时 schema 里跑，因此可以放心 `downgrade base`
再 `upgrade head`，不影响别的用例。

`alembic_version` 是迁移自己的记账表，不属于业务表，比对时单独摘出来。
"""

from __future__ import annotations

from alembic import command
from sqlalchemy import text

from app.db import Base, init_db, session_scope
from app.db.init import alembic_config

# 导入即注册表元数据（与 `app.main` 的装配顺序一致），否则 `Base.metadata` 是空的。
from app.instrument import Instrument  # noqa: F401
from app.market import Candle  # noqa: F401
from app.watchlist import WatchlistItemRow  # noqa: F401

BOOKKEEPING = "alembic_version"


def _tables() -> set[str]:
    with session_scope() as session:
        return set(
            session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema()"
                )
            ).scalars()
        )


def test_upgrade_head_creates_exactly_the_model_tables() -> None:
    init_db()

    assert _tables() - {BOOKKEEPING} == set(Base.metadata.tables)


def test_downgrade_base_then_upgrade_restores_every_table() -> None:
    init_db()
    command.downgrade(alembic_config(), "base")

    assert _tables() <= {BOOKKEEPING}

    init_db()

    assert _tables() - {BOOKKEEPING} == set(Base.metadata.tables)


def test_init_db_is_idempotent() -> None:
    init_db()
    init_db()

    with session_scope() as session:
        versions = session.execute(text("SELECT version_num FROM alembic_version")).scalars().all()

    assert versions == ["0004"]

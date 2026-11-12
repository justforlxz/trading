"""迁移链与模型的一致性：正向建出全部表、反向删干净、重复执行无副作用。

每个用例都在根 `conftest.py` 给的独立临时 schema 里跑，因此可以放心 `downgrade base`
再 `upgrade head`，不影响别的用例。

`alembic_version` 是迁移自己的记账表，不属于业务表，比对时单独摘出来。
"""

from __future__ import annotations

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text

# 导入即注册表元数据（与 `app.main` 的装配顺序一致），否则 `Base.metadata` 是空的。
from app.backtest import (  # noqa: F401
    BacktestEquityRow,
    BacktestRunRow,
    BacktestTradeRow,
)
from app.db import Base, init_db, session_scope
from app.db.init import alembic_config
from app.exchange import OrderSubmission  # noqa: F401
from app.instrument import Instrument  # noqa: F401
from app.market import Candle  # noqa: F401
from app.portfolio import (  # noqa: F401
    AllocationRow,
    PortfolioAdjustmentRow,
    VirtualFillRow,
    VirtualPositionRow,
)
from app.strategy import (  # noqa: F401
    StrategyApprovalRow,
    StrategyInstanceRow,
    StrategyReplayRow,
    StrategyTemplateRow,
)
from app.watchlist import WatchlistItemRow  # noqa: F401

BOOKKEEPING = "alembic_version"


def _migration_heads() -> list[str]:
    """迁移目录里的 head 版本；断言头版本时以它为准，不在用例里写死序号。"""

    return list(ScriptDirectory.from_config(alembic_config()).get_heads())


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

    assert versions == _migration_heads()


def test_migration_chain_has_exactly_one_head() -> None:
    heads = _migration_heads()

    assert len(heads) == 1, f"迁移链存在多个 head: {heads}"


def test_upgrade_removes_backtest_runs_that_cannot_describe_their_instrument() -> None:
    """0010 之前的回测行没有标的与完整请求，升级时必须删掉而不是塞空值。

    这类行无法投影成 `BacktestRunSummary` / `BacktestRequest`：留着会让列表与详情
    接口在存在历史数据时返回 500。升级完再插入新行仍然可行（新列是 NOT NULL 但不再
    依赖数据库默认值）。
    """

    command.upgrade(alembic_config(), "0009")
    with session_scope() as session:
        session.execute(
            text(
                """
                INSERT INTO backtest_runs (
                    run_id, strategy_instance_id, strategy_id, strategy_version,
                    params_json, bar, start_date, end_date, data_source,
                    data_fingerprint, execution_model, costs_json, metrics_json,
                    portfolio_json, funding_total, result_hash, created_at
                ) VALUES (
                    'bt_legacy', 'si_legacy', 'relative_value', '1.0.0',
                    '{}', '1d', '2026-11-01', '2026-11-02', 'okx',
                    'fingerprint', 'next_open', '{}', '{}', '{}', '0', 'hash', 0
                )
                """
            )
        )

    command.upgrade(alembic_config(), "0010")

    with session_scope() as session:
        remaining = session.execute(text("SELECT COUNT(*) FROM backtest_runs")).scalar_one()

    assert remaining == 0

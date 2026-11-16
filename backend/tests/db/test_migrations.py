"""迁移链与模型的一致性：正向建出全部表、反向删干净、重复执行无副作用。

每个用例都在根 `conftest.py` 给的独立临时 schema 里跑，因此可以放心 `downgrade base`
再 `upgrade head`，不影响别的用例。

`alembic_version` 是迁移自己的记账表，不属于业务表，比对时单独摘出来。
"""

from __future__ import annotations

from datetime import datetime

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text

# 导入即注册表元数据（与 `app.main` 的装配顺序一致），否则 `Base.metadata` 是空的。
from app.activity import ActivityEventRow  # noqa: F401
from app.alerts import AlertEventRow  # noqa: F401
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
from app.positions import (  # noqa: F401
    AccountSnapshotRow,
    ExchangePositionSnapshotRow,
    ManualPositionRow,
    ManualTradeRow,
    PositionRiskConfigRow,
)
from app.research import ResearchNoteRow  # noqa: F401
from app.strategy import (  # noqa: F401
    StrategyApprovalRow,
    StrategyInstanceRow,
    StrategyInstrumentRow,
    StrategyLinkedBacktestRow,
    StrategyReplayRow,
    StrategyTemplateRow,
    StrategyVersionRow,
    UserStrategyRow,
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


def test_positions_migration_creates_snapshot_and_manual_tables() -> None:
    """0015 建出账户、持仓、手动流水表，并给 `instruments` 加上 `sector` 列。"""

    init_db()

    assert {
        "account_snapshots",
        "exchange_position_snapshots",
        "manual_positions",
        "manual_trades",
        "position_risk_config",
    } <= _tables()
    with session_scope() as session:
        sector = session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'instruments' AND column_name = 'sector'"
            )
        ).scalar_one_or_none()
    assert sector == "sector"


def test_strategies_migration_creates_versions_instruments_and_links() -> None:
    """0016 建出用户策略、版本、标的关联与回测关联四张表。"""

    init_db()

    assert {
        "strategies",
        "strategy_versions",
        "strategy_instruments",
        "strategy_linked_backtests",
    } <= _tables()
    with session_scope() as session:
        unique = session.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.table_constraints "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'strategy_versions' "
                "AND constraint_type = 'UNIQUE'"
            )
        ).scalar_one()
    assert unique >= 1


def test_research_alerts_activity_migration_and_legacy_price_alerts_removed() -> None:
    """0017 建出研究记录、提醒与活动三张表，并删除旧价格提醒表。"""

    init_db()

    tables = _tables()
    assert {"research_notes", "alert_events", "activity_events"} <= tables
    assert "price_alerts" not in tables
    with session_scope() as session:
        unique = session.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.table_constraints "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'alert_events' "
                "AND constraint_type = 'UNIQUE'"
            )
        ).scalar_one()
    assert unique >= 1


def test_external_market_tables_are_removed_at_head() -> None:
    """0018 建出的外部事件与新闻表，在 0020 之后不再存在；同步任务表保留。"""

    init_db()

    tables = _tables()
    assert "data_sync_jobs" in tables
    assert "market_events" not in tables
    assert "news_items" not in tables
    with session_scope() as session:
        columns = set(
            session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'settings'"
                )
            ).scalars()
        )
    assert {"display", "risk_defaults", "data_sources"} <= columns
    assert "data" not in columns


def test_0020_removes_external_sync_data_proxy_rows_and_provider_setting() -> None:
    """0020 只保留 OKX 同步数据集与 OKX K 线，并清掉设置里的 Provider 键。"""

    command.upgrade(alembic_config(), "0019")
    with session_scope() as session:
        session.execute(
            text(
                """
                INSERT INTO data_sync_jobs
                    (id, provider, dataset, status, started_at, rows)
                VALUES
                    ('job-overview', 'external', 'market_overview', 'succeeded',
                     '2026-11-16 01:00:00', 0),
                    ('job-events', 'external', 'market_events', 'succeeded',
                     '2026-11-16 01:00:00', 0),
                    ('job-news', 'external', 'news', 'succeeded',
                     '2026-11-16 01:00:00', 0),
                    ('job-candles', 'okx', 'candles', 'succeeded',
                     '2026-11-16 01:00:00', 10)
                """
            )
        )
        session.execute(
            text(
                """
                INSERT INTO candles
                    (symbol, bar, open_time, source, open, high, low, close, volume,
                     updated_at, market_session)
                VALUES
                    ('AAPL-USDT-SWAP', '1h', 1764160800, 'us_equity_proxy',
                     '100', '101', '99', '100.5', '10', 1764160800, 'regular'),
                    ('AAPL-USDT-SWAP', '1h', 1764160800, 'okx_swap',
                     '100', '101', '99', '100.5', '10', 1764160800, 'regular'),
                    ('BTC-USDT', '1h', 1764160800, 'okx_spot',
                     '100', '101', '99', '100.5', '10', 1764160800, 'regular')
                """
            )
        )
        session.execute(
            text(
                """
                INSERT INTO settings
                    (id, execution, risk, costs, backtest, updated_at,
                     display, risk_defaults, data_sources)
                VALUES
                    (1, '{}', '{}', '{}', '{}', '2026-11-16 01:00:00', '{}', '{}',
                     '{"provider": "yahoo", "subscribed_instruments": ["BTC-USDT"]}')
                """
            )
        )

    command.upgrade(alembic_config(), "head")

    with session_scope() as session:
        datasets = set(session.execute(text("SELECT dataset FROM data_sync_jobs")).scalars())
        sources = set(session.execute(text("SELECT source FROM candles")).scalars())
        data_sources = session.execute(text("SELECT data_sources FROM settings")).scalar_one()

    assert datasets == {"candles"}
    assert sources == {"okx_swap", "okx_spot"}
    assert "provider" not in data_sources


def test_account_snapshot_migration_backfills_position_batch_marker() -> None:
    """0019 按同一采集时刻的持仓行回填标记，没有持仓行的历史快照保持未知。"""

    command.upgrade(alembic_config(), "0018")
    with session_scope() as session:
        session.execute(
            text(
                """
                INSERT INTO account_snapshots
                    (account_id, currency, equity, available_equity, cash_balance,
                     unrealized_pnl, used_margin, available_margin, margin_ratio,
                     captured_at, source)
                VALUES
                    ('okx-main', 'USDT', '100', '100', '100', '0', '0', '100', '0',
                     '2026-11-13 09:00:00', 'okx_rest'),
                    ('okx-main', 'USDT', '100', '100', '100', '0', '0', '100', '0',
                     '2026-11-13 09:05:00', 'okx_ws')
                """
            )
        )
        session.execute(
            text(
                """
                INSERT INTO exchange_position_snapshots
                    (account_id, pos_id, inst_id, pos_side, size, avg_px,
                     captured_at, source)
                VALUES
                    ('okx-main', '1', 'AAPL-USDT-SWAP', 'long', '8', '226.80',
                     '2026-11-13 09:00:00', 'okx_rest')
                """
            )
        )

    command.upgrade(alembic_config(), "head")

    with session_scope() as session:
        rows = session.execute(
            text(
                "SELECT captured_at, positions_included FROM account_snapshots ORDER BY captured_at"
            )
        ).all()

    assert [(row.captured_at, row.positions_included) for row in rows] == [
        (datetime(2026, 11, 13, 9, 0), True),
        (datetime(2026, 11, 13, 9, 5), False),
    ]

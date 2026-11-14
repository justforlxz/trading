"""Alembic 迁移环境。

连接不另起一套：迁移与业务代码共用 `app.db.engine.get_engine()`，因此
`DATABASE_URL` 与 `DATABASE_SCHEMA` 只有一份值，测试的临时 schema 里也能跑迁移。

域模型在这里显式导入一次，`--autogenerate` 才能看到全部表（与 `app.main` 的装配
路径一致）；迁移脚本本身不导入应用代码，历史脚本因此不会随实现变化而改变。
"""

from alembic import context

from app.db import Base

# 导入即注册表元数据（与 `app.main` 的装配顺序一致）。
from app.exchange import OrderSubmission  # noqa: F401
from app.instrument import Instrument  # noqa: F401
from app.market import Candle, CorrelationSnapshot  # noqa: F401
from app.positions import (  # noqa: F401
    AccountSnapshotRow,
    ExchangePositionSnapshotRow,
    ManualPositionRow,
    ManualTradeRow,
    PositionRiskConfigRow,
)
from app.strategy import (  # noqa: F401
    StrategyInstanceRow,
    StrategyInstrumentRow,
    StrategyLinkedBacktestRow,
    StrategyTemplateRow,
    StrategyVersionRow,
    UserStrategyRow,
)
from app.watchlist import WatchlistItemRow  # noqa: F401

target_metadata = Base.metadata


def run_migrations_online() -> None:
    """在应用的引擎上执行迁移。"""

    from app.db.engine import get_engine  # 延迟导入：离线检查时不需要连接配置。

    with get_engine().connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("不支持 offline 模式: 迁移连接由应用引擎提供, 无法只输出 SQL")

run_migrations_online()

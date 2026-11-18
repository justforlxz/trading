"""FastAPI 应用入口：`uvicorn app.main:app`（cwd = 仓库根）。

v2 是单进程同步栈：一个 uvicorn 进程、一个 PostgreSQL 库、没有消息队列与独立 worker。
装配顺序即分层顺序：配置 → 数据库 → HTTP 协议层。
"""

import asyncio
import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from threading import Event
from typing import Any

from fastapi import FastAPI

from app import __version__
from app.activity import ActivityEventRow, set_event_publisher  # noqa: F401
from app.alerts import AlertEventRow  # noqa: F401
from app.api import include_routers, register_error_handlers

# 导入即注册域模型：迁移只认得已注册的元数据，装配根负责把域模型拉进来。
from app.backtest import (  # noqa: F401
    BacktestEquityRow,
    BacktestRunRow,
    BacktestTradeRow,
)
from app.config import get_settings
from app.db import init_db
from app.exchange import OrderSubmission  # noqa: F401
from app.instrument import Instrument  # noqa: F401
from app.jobs import OnDemandSyncScheduler, start_equity_snapshot_scheduler
from app.journal import ExecutionSnapshot
from app.market import (  # noqa: F401
    Candle,
    DataSyncJobRow,
)
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
from app.settings import SettingsRow, apply_saved_settings  # noqa: F401
from app.strategy import (  # noqa: F401
    StrategyInstanceRow,
    StrategyInstrumentRow,
    StrategyLinkedBacktestRow,
    StrategyReplayRow,
    StrategyTemplateRow,
    StrategyVersionRow,
    UserStrategyRow,
)
from app.stream import StreamHub
from app.watchlist import WatchlistItemRow  # noqa: F401

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> Iterator[None]:
    """启动时把库结构推进到最新版本；退出无需清理（连接池随进程关闭）。"""

    init_db()
    apply_saved_settings()
    stop_scheduler = Event()
    scheduler = start_equity_snapshot_scheduler(stop_scheduler)
    hub = StreamHub()
    _app.state.stream_hub = hub
    loop = asyncio.get_running_loop()

    def _publish(event_type: str, data: dict[str, Any], as_of: datetime | None) -> None:
        """把业务包提交后的事件调度到推送循环；调用方不等待发送结果。"""

        asyncio.run_coroutine_threadsafe(hub.publish(event_type, data, as_of=as_of), loop)

    set_event_publisher(_publish)
    logger.info("trading api ready: version=%s", __version__)
    try:
        yield
    finally:
        set_event_publisher(None)
        stop_scheduler.set()
        scheduler.join(timeout=5.0)
        _app.state.on_demand_sync.shutdown()
        await hub.stop()


def create_app(*, on_demand_sync: OnDemandSyncScheduler | None = None) -> FastAPI:
    """构造应用实例：测试与生产共用同一装配路径。

    `on_demand_sync` 只供测试注入可控的同步调度器；生产路径按配置创建真实队列。
    """

    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    app = FastAPI(
        title="trading",
        version=__version__,
        description="个人量化工作台 — v2 单进程骨架",
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    register_error_handlers(app)
    # Trades 页读取的执行事实。执行编排（T6.2）每完成一次下单或同步就替换这份快照；
    # 还没有执行编排时保持空快照，页面如实显示空状态，不编造持仓、订单或成交。
    app.state.execution_snapshot = ExecutionSnapshot()
    app.state.on_demand_sync = on_demand_sync or OnDemandSyncScheduler(
        max_concurrency=settings.on_demand_sync_max_concurrency
    )
    include_routers(app)
    return app


app = create_app()

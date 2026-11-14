"""HTTP 路由装配：一个域一个路由模块，这里只登记，不承载任何端点。"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.contract import contract_router
from app.api.health import router as health_router
from app.api.routes.approval import approval_router
from app.api.routes.backtest import backtest_router
from app.api.routes.dashboard import dashboard_router
from app.api.routes.indicators import indicators_router
from app.api.routes.instruments import instruments_router
from app.api.routes.market import market_router
from app.api.routes.opportunity import opportunity_router
from app.api.routes.positions import positions_router
from app.api.routes.risk import risk_exposure_router
from app.api.routes.settings import settings_router
from app.api.routes.strategy import strategy_router
from app.api.routes.stream import stream_router
from app.api.routes.watchlist import watchlist_router

__all__ = ["include_routers"]


def include_routers(app: FastAPI) -> None:
    """把所有域挂到同一个 `/api` 前缀下；尚未实现的域仍由契约桩应答。"""

    app.include_router(health_router, prefix="/api")
    app.include_router(watchlist_router, prefix="/api")
    app.include_router(instruments_router, prefix="/api")
    app.include_router(indicators_router, prefix="/api")
    app.include_router(market_router, prefix="/api")
    app.include_router(opportunity_router, prefix="/api")
    app.include_router(dashboard_router, prefix="/api")
    app.include_router(strategy_router, prefix="/api")
    app.include_router(approval_router, prefix="/api")
    app.include_router(backtest_router, prefix="/api")
    app.include_router(positions_router, prefix="/api")
    app.include_router(risk_exposure_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(stream_router, prefix="/api")
    app.include_router(contract_router, prefix="/api")

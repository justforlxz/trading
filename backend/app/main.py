"""FastAPI 应用入口：`uvicorn app.main:app`（cwd = 仓库根）。

v2 是单进程同步栈：一个 uvicorn 进程、一个 SQLite 文件、没有消息队列与独立 worker。
装配顺序即分层顺序：配置 → 数据库 → HTTP 协议层。
"""

import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import contract_router, health_router
from app.config import get_settings
from app.db import init_db

# 导入即注册 `candles` 表：建表只认已经定义过的元数据，装配根负责把域模型拉进来。
from app.market import Candle  # noqa: F401

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> Iterator[None]:
    """启动时就地建库建表；退出无需清理（SQLite 连接随进程关闭）。"""

    init_db()
    logger.info("trading api ready: version=%s", __version__)
    yield


def create_app() -> FastAPI:
    """构造应用实例：测试与生产共用同一装配路径。"""

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
    app.include_router(health_router, prefix="/api")
    app.include_router(contract_router, prefix="/api")
    return app


app = create_app()

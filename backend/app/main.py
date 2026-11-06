"""FastAPI 应用入口：`uvicorn app.main:app`。

装配顺序即分层顺序：运维探针 → `/api/v1` 协议层。业务模块在 S3 起注册。
"""

import logging

from fastapi import FastAPI

from app import __version__
from app.api.v1 import router as api_v1_router
from app.config import get_settings
from app.ops.health import router as ops_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """构造应用实例（测试与生产共用，避免导入即建连）。"""

    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    app = FastAPI(
        title="trading",
        version=__version__,
        description="自托管美股永续量化交易系统 — P1 骨架",
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.include_router(ops_router)
    app.include_router(api_v1_router)
    logger.info("trading api initialized: env=%s version=%s", settings.app_env, __version__)
    return app


app = create_app()

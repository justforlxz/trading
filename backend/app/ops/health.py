"""存活与就绪探针（`/health`、`/ready`，均不带版本前缀，见 api-contract §3.1）。"""

import logging
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.db.session import engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ops"])


@router.get("/health")
async def health() -> dict[str, str]:
    """存活探针：只证明进程在跑，不查数据库。"""

    return {"status": "ok", "version": __version__}


@router.get("/ready", response_model=None)
async def ready() -> JSONResponse | dict[str, str]:
    """就绪探针：数据库可连通返回 200，否则 503（错误信封见 api-contract §1.1）。"""

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        logger.exception("readiness check failed: database is not reachable")
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "dependency_unavailable",
                    "message": "database is not reachable",
                    "details": {},
                    "request_id": str(uuid4()),
                }
            },
        )
    return {"status": "ok"}

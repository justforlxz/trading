"""`/api/v1` 路由装配。

S3 挂载 market 与 ops；其余资源（targets/opportunities/strategies/backtests）
按 `docs/plan/p1.md` 在后续阶段加入，语义以 `docs/architecture/api-contract.md` 为准。
"""

from fastapi import APIRouter

from app import __version__
from app.api.v1 import market, ops

router = APIRouter(prefix="/api/v1", tags=["ops"])
router.include_router(market.router)
router.include_router(ops.router)


@router.get("")
async def api_root() -> dict[str, str]:
    """API 根：供脚本与前端探活确认版本前缀已挂载。"""

    return {"name": "trading", "version": __version__}

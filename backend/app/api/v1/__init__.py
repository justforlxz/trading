"""`/api/v1` 路由前缀占位。

S2 只挂载前缀与自述端点；业务资源（market/targets/opportunities/strategies/
backtests/ops）按 `docs/plan/p1.md` 在 S3 起逐个加入，路由语义以
`docs/architecture/api-contract.md` 为准。
"""

from fastapi import APIRouter

from app import __version__

router = APIRouter(prefix="/api/v1", tags=["ops"])


@router.get("")
async def api_root() -> dict[str, str]:
    """API 根：供脚本与前端探活确认版本前缀已挂载。"""

    return {"name": "trading", "version": __version__}

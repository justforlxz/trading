"""`/api/v1` 路由装配。

挂载 market、ops、research（目标股票/关系分析）、opportunity（全市场扫描）、
strategy（策略生成与审批）、backtest（历史回测与评估）与 risk（P2 风控）。
语义以 `docs/architecture/api-contract.md` 为准。
"""

from fastapi import APIRouter

from app import __version__
from app.api.v1 import backtest, execution, market, ops, research, risk
from app.opportunity import api as opportunity_api
from app.strategy import api as strategy_api

router = APIRouter(prefix="/api/v1", tags=["ops"])
router.include_router(market.router)
router.include_router(ops.router)
router.include_router(research.router)
router.include_router(opportunity_api.router)
router.include_router(opportunity_api.cluster_router)
router.include_router(opportunity_api.market_router)
router.include_router(strategy_api.router)
router.include_router(backtest.router)
router.include_router(risk.router)
router.include_router(execution.router)


@router.get("")
async def api_root() -> dict[str, str]:
    """API 根：供脚本与前端探活确认版本前缀已挂载。"""

    return {"name": "trading", "version": __version__}

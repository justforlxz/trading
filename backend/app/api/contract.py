"""各业务域的 HTTP 契约桩。

这里的每个端点只负责「路径 + 请求模型 + 响应模型」的绑定，函数体一律抛
501，不含任何业务逻辑。它存在的唯一目的是把契约冻结进
`contracts/openapi.json`，让前端可以对着 MSW 假后端独立开发。

实现某个域的节点落地真实端点时，删除该域的桩，不允许两套并存。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime

from app.api.schemas import (
    BacktestDetailResponse,
    BacktestRankingResponse,
    BacktestRequest,
    BacktestRunListResponse,
    BacktestRunSummary,
    BacktestSweepRequest,
    BacktestSweepResponse,
    CorrelationMatrixResponse,
    CorrelationSeriesResponse,
    ExecutionModeRequest,
    ExecutionStateResponse,
    ExposureOverviewResponse,
    FillListResponse,
    JournalListResponse,
    LiveAuthorizationRequest,
    MarketOverviewResponse,
    Opportunity,
    OpportunityListResponse,
    OpportunityMode,
    OpportunityStatus,
    OpportunityStatusUpdateRequest,
    Order,
    OrderCreateRequest,
    OrderListResponse,
    OverviewResponse,
    PortfolioAdjustment,
    PortfolioAdjustmentCreateRequest,
    PortfolioAdjustmentDecisionRequest,
    PortfolioAdjustmentListResponse,
    PositionListResponse,
    RankingMetric,
    RelationGraphResponse,
    RelationNeighborsResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    SignalListResponse,
    StrategyApprovalDecisionRequest,
    StrategyApprovalListResponse,
    StrategyApprovalRequest,
    StrategyApprovalTransition,
    StrategyCatalogResponse,
    StrategyInstance,
    StrategyInstanceCreateRequest,
    StrategyInstanceListResponse,
    StrategyInstanceUpdateRequest,
    StrategyPortfolioDetailResponse,
    StrategyPortfolioListResponse,
)
from app.api.schemas.common import Bar, DataSource, InstType

__all__ = ["contract_router"]

contract_router = APIRouter()


def _stub(node: str) -> HTTPException:
    """契约桩统一响应：501 明确表示「形状已定、实现未到」。"""

    return HTTPException(status_code=501, detail=f"contract stub; implemented by {node}")


# ---------------------------------------------------------------- strategy

strategy_router = APIRouter(tags=["strategy"])


@strategy_router.get("/strategies", response_model=StrategyCatalogResponse)
def list_strategies() -> StrategyCatalogResponse:
    raise _stub("T3.1")


@strategy_router.get("/strategy-instances", response_model=StrategyInstanceListResponse)
def list_strategy_instances() -> StrategyInstanceListResponse:
    raise _stub("T3.3")


@strategy_router.post("/strategy-instances", response_model=StrategyInstance, status_code=201)
def create_strategy_instance(payload: StrategyInstanceCreateRequest) -> StrategyInstance:
    raise _stub("T3.3")


@strategy_router.get("/strategy-instances/{instance_id}", response_model=StrategyInstance)
def get_strategy_instance(instance_id: str) -> StrategyInstance:
    raise _stub("T3.3")


@strategy_router.patch("/strategy-instances/{instance_id}", response_model=StrategyInstance)
def update_strategy_instance(
    instance_id: str, payload: StrategyInstanceUpdateRequest
) -> StrategyInstance:
    raise _stub("T3.3")


@strategy_router.delete("/strategy-instances/{instance_id}", status_code=204, response_model=None)
def delete_strategy_instance(instance_id: str) -> None:
    raise _stub("T3.3")


# ---------------------------------------------------------------- backtest

backtest_router = APIRouter(tags=["backtest"])


@backtest_router.get("/backtests/ranking", response_model=BacktestRankingResponse)
def get_backtest_ranking(
    data_source: DataSource = Query(...),
    metric: RankingMetric = Query("total_return_pct"),
    limit: int = Query(50, ge=1, le=500),
) -> BacktestRankingResponse:
    raise _stub("T4.3")


@backtest_router.post("/backtests", response_model=BacktestRunSummary, status_code=202)
def create_backtest(payload: BacktestRequest) -> BacktestRunSummary:
    raise _stub("T4.4")


@backtest_router.get("/backtests", response_model=BacktestRunListResponse)
def list_backtests(
    data_source: DataSource = Query(...),
    limit: int = Query(50, ge=1, le=200),
) -> BacktestRunListResponse:
    raise _stub("T4.4")


@backtest_router.get("/backtests/{run_id}", response_model=BacktestDetailResponse)
def get_backtest(run_id: str) -> BacktestDetailResponse:
    raise _stub("T4.4")


@backtest_router.delete("/backtests/{run_id}", status_code=204, response_model=None)
def delete_backtest(run_id: str) -> None:
    raise _stub("T4.4")


@backtest_router.post("/backtest-sweeps", response_model=BacktestSweepResponse, status_code=202)
def create_backtest_sweep(payload: BacktestSweepRequest) -> BacktestSweepResponse:
    raise _stub("T4.3")


# ---------------------------------------------------------------- trades

trades_router = APIRouter(tags=["trades"])


@trades_router.get("/trades/positions", response_model=PositionListResponse)
def list_positions() -> PositionListResponse:
    raise _stub("T5.2")


@trades_router.get("/trades/orders", response_model=OrderListResponse)
def list_orders() -> OrderListResponse:
    raise _stub("T5.2")


@trades_router.post("/trades/orders", response_model=Order, status_code=201)
def create_order(payload: OrderCreateRequest) -> Order:
    raise _stub("T5.3")


@trades_router.delete("/trades/orders/{order_id}", status_code=204, response_model=None)
def cancel_order(order_id: str) -> None:
    raise _stub("T5.3")


@trades_router.get("/trades/fills", response_model=FillListResponse)
def list_fills() -> FillListResponse:
    raise _stub("T5.2")


@trades_router.get("/signals", response_model=SignalListResponse)
def list_signals() -> SignalListResponse:
    raise _stub("T5.4")


@trades_router.get("/journal", response_model=JournalListResponse)
def list_journal() -> JournalListResponse:
    raise _stub("T5.4")


@trades_router.get("/execution", response_model=ExecutionStateResponse)
def get_execution_state() -> ExecutionStateResponse:
    raise _stub("T5.3")


@trades_router.put("/execution/mode", response_model=ExecutionStateResponse)
def set_execution_mode(payload: ExecutionModeRequest) -> ExecutionStateResponse:
    raise _stub("T5.3")


# ---------------------------------------------------------------- settings

settings_router = APIRouter(tags=["settings"])


@settings_router.get("/settings", response_model=SettingsResponse)
def get_settings_document() -> SettingsResponse:
    raise _stub("T5.5")


@settings_router.put("/settings", response_model=SettingsResponse)
def update_settings_document(payload: SettingsUpdateRequest) -> SettingsResponse:
    raise _stub("T5.5")


# ---------------------------------------------------------------- overview

overview_router = APIRouter(tags=["overview"])


@overview_router.get("/overview", response_model=OverviewResponse)
def get_overview() -> OverviewResponse:
    raise _stub("T6.4")


# ---------------------------------------------------------------- correlation

# 三个只读端点的 `as_of` 缺省表示「最近一次快照」，给出时按该时刻回看。
# 类型用 `AwareDatetime`：不带时区的时间直接 422，不接受本地时间被当成 UTC。

correlation_router = APIRouter(tags=["correlation"])


@correlation_router.get("/correlation/matrix", response_model=CorrelationMatrixResponse)
def get_correlation_matrix(
    product_keys: list[str] = Query(..., min_length=1),
    bar: Bar = Query(...),
    window: int = Query(..., ge=2, le=250),
    as_of: AwareDatetime | None = Query(None),
) -> CorrelationMatrixResponse:
    raise _stub("T2.3")


@correlation_router.get("/correlation/series", response_model=CorrelationSeriesResponse)
def get_correlation_series(
    product_key_a: str = Query(...),
    product_key_b: str = Query(...),
    bar: Bar = Query(...),
    window: int = Query(..., ge=2, le=250),
) -> CorrelationSeriesResponse:
    raise _stub("T2.3")


# 横截面按类别分开统计，`inst_type` 必填：两类标的的交易时段不同，不能混在一起。
@correlation_router.get("/market/overview", response_model=MarketOverviewResponse)
def get_market_overview(
    inst_type: InstType = Query(...),
    bar: Bar = Query("1d"),
    as_of: AwareDatetime | None = Query(None),
) -> MarketOverviewResponse:
    raise _stub("T2.5")


# ---------------------------------------------------------------- relations

relations_router = APIRouter(tags=["relations"])


@relations_router.get("/relations/graph", response_model=RelationGraphResponse)
def get_relation_graph(
    bar: Bar = Query(...),
    window: int = Query(..., ge=2, le=250),
    min_abs_corr: float = Query(0.5, ge=0, le=1),
    as_of: AwareDatetime | None = Query(None),
) -> RelationGraphResponse:
    raise _stub("T2.4")


@relations_router.get("/relations/neighbors", response_model=RelationNeighborsResponse)
def get_relation_neighbors(
    product_key: str = Query(...),
    bar: Bar = Query(...),
    window: int = Query(..., ge=2, le=250),
    min_abs_corr: float = Query(0.5, ge=0, le=1),
) -> RelationNeighborsResponse:
    raise _stub("T2.4")


# ---------------------------------------------------------------- opportunity

opportunity_router = APIRouter(tags=["opportunity"])


@opportunity_router.get("/opportunities", response_model=OpportunityListResponse)
def list_opportunities(
    mode: OpportunityMode | None = Query(None),
    anchor_product_key: str | None = Query(None),
    status: OpportunityStatus | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> OpportunityListResponse:
    raise _stub("T3.4")


@opportunity_router.get("/opportunities/{opportunity_id}", response_model=Opportunity)
def get_opportunity(opportunity_id: str) -> Opportunity:
    raise _stub("T3.4")


@opportunity_router.patch("/opportunities/{opportunity_id}", response_model=Opportunity)
def update_opportunity_status(
    opportunity_id: str, payload: OpportunityStatusUpdateRequest
) -> Opportunity:
    raise _stub("T3.4")


# ---------------------------------------------------------------- portfolio

portfolio_router = APIRouter(tags=["portfolio"])


@portfolio_router.get("/portfolio/strategies", response_model=StrategyPortfolioListResponse)
def list_strategy_portfolios() -> StrategyPortfolioListResponse:
    raise _stub("T7.1")


@portfolio_router.get(
    "/portfolio/strategies/{instance_id}", response_model=StrategyPortfolioDetailResponse
)
def get_strategy_portfolio(instance_id: str) -> StrategyPortfolioDetailResponse:
    raise _stub("T7.1")


@portfolio_router.get("/portfolio/exposure", response_model=ExposureOverviewResponse)
def get_portfolio_exposure() -> ExposureOverviewResponse:
    raise _stub("T7.1")


@portfolio_router.get("/portfolio/adjustments", response_model=PortfolioAdjustmentListResponse)
def list_portfolio_adjustments() -> PortfolioAdjustmentListResponse:
    raise _stub("T7.1")


@portfolio_router.post(
    "/portfolio/adjustments", response_model=PortfolioAdjustment, status_code=201
)
def create_portfolio_adjustment(
    payload: PortfolioAdjustmentCreateRequest,
) -> PortfolioAdjustment:
    raise _stub("T7.1")


@portfolio_router.patch(
    "/portfolio/adjustments/{adjustment_id}", response_model=PortfolioAdjustment
)
def decide_portfolio_adjustment(
    adjustment_id: str, payload: PortfolioAdjustmentDecisionRequest
) -> PortfolioAdjustment:
    raise _stub("T7.1")


# ---------------------------------------------------------------- approval

approval_router = APIRouter(tags=["approval"])


@approval_router.get("/approvals", response_model=StrategyApprovalListResponse)
def list_approvals() -> StrategyApprovalListResponse:
    raise _stub("T3.6")


@approval_router.post("/approvals", response_model=StrategyApprovalTransition, status_code=201)
def submit_for_review(payload: StrategyApprovalRequest) -> StrategyApprovalTransition:
    raise _stub("T3.6")


@approval_router.post("/approvals/{instance_id}/approve", response_model=StrategyApprovalTransition)
def approve_strategy(
    instance_id: str, payload: StrategyApprovalDecisionRequest
) -> StrategyApprovalTransition:
    raise _stub("T3.6")


@approval_router.post("/approvals/{instance_id}/reject", response_model=StrategyApprovalTransition)
def reject_strategy(
    instance_id: str, payload: StrategyApprovalDecisionRequest
) -> StrategyApprovalTransition:
    raise _stub("T3.6")


@approval_router.post(
    "/approvals/{instance_id}/live-authorization",
    response_model=StrategyApprovalTransition,
)
def authorize_live_trading(
    instance_id: str, payload: LiveAuthorizationRequest
) -> StrategyApprovalTransition:
    raise _stub("T3.6")


for _router in (
    strategy_router,
    backtest_router,
    trades_router,
    settings_router,
    overview_router,
    correlation_router,
    relations_router,
    opportunity_router,
    portfolio_router,
    approval_router,
):
    contract_router.include_router(_router)

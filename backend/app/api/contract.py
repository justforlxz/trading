"""七个业务域的 HTTP 契约桩。

这里的每个端点只负责「路径 + 请求模型 + 响应模型」的绑定，函数体一律抛
501，不含任何业务逻辑。它存在的唯一目的是把契约冻结进
`contracts/openapi.json`，让前端可以对着 MSW 假后端独立开发。

实现某个域的节点落地真实端点时，删除该域的桩，不允许两套并存。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas import (
    BacktestDetailResponse,
    BacktestRankingResponse,
    BacktestRequest,
    BacktestRunListResponse,
    BacktestRunSummary,
    BacktestSweepRequest,
    BacktestSweepResponse,
    CandleSeriesResponse,
    ExecutionModeRequest,
    ExecutionStateResponse,
    FillListResponse,
    IndicatorCatalogResponse,
    IndicatorSeriesResponse,
    InstrumentDetailResponse,
    InstrumentSearchResponse,
    JournalListResponse,
    Order,
    OrderCreateRequest,
    OrderListResponse,
    OverviewResponse,
    PositionListResponse,
    PriceAlert,
    PriceAlertRequest,
    RankingMetric,
    RelatedInstrumentsResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    SignalListResponse,
    StrategyCatalogResponse,
    StrategyInstance,
    StrategyInstanceCreateRequest,
    StrategyInstanceListResponse,
    StrategyInstanceUpdateRequest,
    WatchlistAddRequest,
    WatchlistItem,
    WatchlistResponse,
    WatchlistUpdateRequest,
)
from app.api.schemas.common import Bar, DataSource, InstType

__all__ = ["contract_router"]

contract_router = APIRouter()


def _stub(node: str) -> HTTPException:
    """契约桩统一响应：501 明确表示「形状已定、实现未到」。"""

    return HTTPException(status_code=501, detail=f"contract stub; implemented by {node}")


# ---------------------------------------------------------------- watchlist

watchlist_router = APIRouter(tags=["watchlist"])


@watchlist_router.get("/watchlist", response_model=WatchlistResponse)
def list_watchlist() -> WatchlistResponse:
    raise _stub("T1.5")


@watchlist_router.post("/watchlist", response_model=WatchlistItem, status_code=201)
def add_watchlist_item(payload: WatchlistAddRequest) -> WatchlistItem:
    raise _stub("T1.5")


@watchlist_router.get("/watchlist/{inst_id}/related", response_model=RelatedInstrumentsResponse)
def get_related_instruments(inst_id: str, window_days: int = Query(30, ge=5, le=180)):
    raise _stub("T2.2")


@watchlist_router.put("/watchlist/{inst_id}/alert", response_model=PriceAlert)
def put_price_alert(inst_id: str, payload: PriceAlertRequest) -> PriceAlert:
    raise _stub("T1.5")


@watchlist_router.delete("/watchlist/{inst_id}/alert", status_code=204, response_model=None)
def delete_price_alert(inst_id: str) -> None:
    raise _stub("T1.5")


@watchlist_router.patch("/watchlist/{inst_id}", response_model=WatchlistItem)
def update_watchlist_item(inst_id: str, payload: WatchlistUpdateRequest) -> WatchlistItem:
    raise _stub("T1.5")


@watchlist_router.delete("/watchlist/{inst_id}", status_code=204, response_model=None)
def delete_watchlist_item(inst_id: str) -> None:
    raise _stub("T1.5")


@watchlist_router.get("/instruments/search", response_model=InstrumentSearchResponse)
def search_instruments(
    q: str = Query(..., min_length=1),
    inst_type: InstType | None = None,
) -> InstrumentSearchResponse:
    raise _stub("T1.3")


@watchlist_router.get("/instruments/{inst_id}", response_model=InstrumentDetailResponse)
def get_instrument(inst_id: str) -> InstrumentDetailResponse:
    raise _stub("T1.3")


@watchlist_router.get("/instruments/{inst_id}/candles", response_model=CandleSeriesResponse)
def get_instrument_candles(
    inst_id: str,
    bar: Bar = Query(...),
    limit: int = Query(200, ge=1, le=1000),
) -> CandleSeriesResponse:
    raise _stub("T1.4")


# ---------------------------------------------------------------- indicators

indicators_router = APIRouter(tags=["indicators"])


@indicators_router.get("/indicators", response_model=IndicatorCatalogResponse)
def list_indicators() -> IndicatorCatalogResponse:
    raise _stub("T2.1")


@indicators_router.get("/indicators/series", response_model=IndicatorSeriesResponse)
def get_indicator_series(
    inst_id: str = Query(...),
    bar: Bar = Query(...),
    names: str = Query(..., description="逗号分隔的指标名 (如 rsi,sma)"),
    limit: int = Query(200, ge=1, le=1000),
) -> IndicatorSeriesResponse:
    raise _stub("T2.2")


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


for _router in (
    watchlist_router,
    indicators_router,
    strategy_router,
    backtest_router,
    trades_router,
    settings_router,
    overview_router,
):
    contract_router.include_router(_router)

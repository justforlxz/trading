"""各业务域的 HTTP 契约。

尚未实现的域只绑定「路径 + 请求模型 + 响应模型」，函数体抛 501；实现某个域的
节点落地真实端点时，删除该域的桩，不允许两套并存。风险事件列表已实现：它只读
`risk_events`，因此直接放在本模块，不再另建路由文件。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime

from app.api.schemas import (
    BacktestSweepRequest,
    BacktestSweepResponse,
    CorrelationMatrixResponse,
    CorrelationSeriesResponse,
    ExecutionModeRequest,
    ExecutionStateResponse,
    FillListResponse,
    JournalListResponse,
    Order,
    OrderCreateRequest,
    OrderListResponse,
    OverviewResponse,
    PositionListResponse,
    RiskEvent,
    RiskEventListResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    SignalListResponse,
)
from app.api.schemas.common import Bar
from app.risk import list_risk_events

__all__ = ["contract_router"]

contract_router = APIRouter()


def _stub(node: str) -> HTTPException:
    """契约桩统一响应：501 明确表示「形状已定、实现未到」。"""

    return HTTPException(status_code=501, detail=f"contract stub; implemented by {node}")


# ---------------------------------------------------------------- backtest

# 参数扫描端点仍是契约桩：T4.3 交付的是扫描的域实现与进程内队列（`app/backtest/sweep.py`、
# `app/jobs/**`），没有落地 HTTP 端点。回测主链路（发起 / 列表 / 排行 / 明细 / 删除）由
# T4.4 实现，见 `app.api.routes.backtest`；两者不共用一条路径，所以这里只留扫描这一条桩。

backtest_router = APIRouter(tags=["backtest"])


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


# ---------------------------------------------------------------- risk

# 风险事件只读列表。分级处置（T6.5）需要的标记动作不在本节点实现。
risk_router = APIRouter(tags=["risk"])


@risk_router.get("/risk/events", response_model=RiskEventListResponse)
def list_risk_event_records(
    instance_id: str | None = Query(None),
    inst_id: str | None = Query(None),
    rule: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
) -> RiskEventListResponse:
    records, total = list_risk_events(
        instance_id=instance_id,
        inst_id=inst_id,
        rule=rule,
        limit=limit,
    )
    return RiskEventListResponse(
        items=[
            RiskEvent(
                event_id=record.event_id,
                instance_id=record.instance_id,
                inst_id=record.inst_id,
                rule=record.rule,
                detail=record.detail,
                created_at=record.created_at,
                resolved_at=record.resolved_at,
            )
            for record in records
        ],
        total=total,
    )


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


# 审批域（`/api/approvals`）已由 `app/api/routes/approval.py` 实现，桩随之删除：
# 契约里同一路径只允许一个处理函数。

for _router in (
    backtest_router,
    trades_router,
    settings_router,
    overview_router,
    correlation_router,
    risk_router,
):
    contract_router.include_router(_router)

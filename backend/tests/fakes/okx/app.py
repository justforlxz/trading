"""假 OKX 的 ASGI 应用。

公共端点（标的、K 线、资金费、行情快照）与私有交易端点（余额、持仓、下单、撤单、
查单、成交）都在这里。应答封包、业务错误码、鉴权与故障注入都按真实上游行为实现，
让适配器能在不改代码的前提下直接指过来。

私有端点先验签再进业务：签名不对返回 HTTP 401 + `50113`，与真实上游一致；逐单失败
返回 HTTP 200 + `code: "1"` + `data[0].sCode`。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from tests.fakes.okx.scenarios import Scenarios
from tests.fakes.okx.store import (
    INVALID_PARAMETER_CODE,
    MAX_CANDLE_LIMIT,
    UNKNOWN_INST_ID_CODE,
    OkxApiError,
    OkxStore,
)
from tests.fakes.okx.trade import (
    INVALID_SIGN_STATUS,
    ORDER_FAILED_CODE,
    OkxAuthError,
    OkxOrderError,
    verify_request,
)

_INSTRUMENTS_PATH = "/api/v5/public/instruments"
_FUNDING_RATE_HISTORY_PATH = "/api/v5/public/funding-rate-history"
_CANDLES_PATH = "/api/v5/market/candles"
_HISTORY_CANDLES_PATH = "/api/v5/market/history-candles"
_TICKER_PATH = "/api/v5/market/ticker"
_BALANCE_PATH = "/api/v5/account/balance"
_POSITIONS_PATH = "/api/v5/account/positions"
_ORDER_PATH = "/api/v5/trade/order"
_CANCEL_ORDER_PATH = "/api/v5/trade/cancel-order"
_FILLS_PATH = "/api/v5/trade/fills"


def okx_payload(data: Any, *, code: str = "0", msg: str = "") -> dict[str, Any]:
    """上游统一封包：`{"code", "msg", "data"}`。"""

    return {"code": code, "msg": msg, "data": data}


def create_app(*, store: OkxStore | None = None, scenarios: Scenarios | None = None) -> FastAPI:
    """装配假 OKX；数据源与故障开关可注入，便于测试固定时钟。

    `python -m tests.fakes.okx.server` 与进程内测试都用这个工厂，
    避免两份路由定义漂移。
    """

    app = FastAPI(title="Fake OKX", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.okx_store = store if store is not None else OkxStore()
    app.state.okx_scenarios = scenarios if scenarios is not None else Scenarios()

    @app.middleware("http")
    async def inject_scenario(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        active: Scenarios = request.app.state.okx_scenarios
        if active.delay_seconds > 0:
            await asyncio.sleep(active.delay_seconds)
        scenario = active.scenario
        if scenario is not None:
            return JSONResponse(
                status_code=scenario.status_code,
                content=okx_payload([], code=scenario.code, msg=scenario.message),
            )
        return await call_next(request)

    @app.get(_INSTRUMENTS_PATH)
    def read_instruments(request: Request, instType: str | None = None) -> dict[str, Any]:
        try:
            return okx_payload(request.app.state.okx_store.instruments(instType or ""))
        except OkxApiError as exc:
            return okx_payload([], code=exc.code, msg=exc.message)

    @app.get(_CANDLES_PATH)
    def read_candles(
        request: Request,
        instId: str | None = None,
        bar: str | None = None,
        limit: str | None = None,
    ) -> dict[str, Any]:
        try:
            rows = request.app.state.okx_store.candles(
                instId or "",
                bar or "",
                _parse_limit(limit, default=MAX_CANDLE_LIMIT),
            )
        except OkxApiError as exc:
            return okx_payload([], code=exc.code, msg=exc.message)
        return okx_payload(rows)

    @app.get(_HISTORY_CANDLES_PATH)
    def read_history_candles(
        request: Request,
        instId: str | None = None,
        bar: str | None = None,
        after: str | None = None,
        limit: str | None = None,
    ) -> dict[str, Any]:
        try:
            rows = request.app.state.okx_store.history_candles(
                instId or "",
                bar or "",
                after=_parse_after(after),
                limit=_parse_limit(limit, default=MAX_CANDLE_LIMIT),
            )
        except OkxApiError as exc:
            return okx_payload([], code=exc.code, msg=exc.message)
        return okx_payload(rows)

    @app.get(_TICKER_PATH)
    def read_ticker(request: Request, instId: str | None = None) -> dict[str, Any]:
        try:
            row = request.app.state.okx_store.ticker(instId or "")
        except OkxApiError as exc:
            return okx_payload([], code=exc.code, msg=exc.message)
        return okx_payload([row])

    @app.get(_FUNDING_RATE_HISTORY_PATH)
    def read_funding_rate_history(
        request: Request,
        instId: str | None = None,
        after: str | None = None,
        limit: str | None = None,
    ) -> dict[str, Any]:
        try:
            rows = request.app.state.okx_store.funding_rate_history(
                instId or "",
                after=_parse_after(after),
                limit=_parse_limit(limit, default=MAX_CANDLE_LIMIT),
            )
        except OkxApiError as exc:
            return okx_payload([], code=exc.code, msg=exc.message)
        return okx_payload(rows)

    @app.get(_BALANCE_PATH)
    def read_balance(request: Request, ccy: str | None = None) -> Any:
        denied = _denied(request)
        if denied is not None:
            return denied
        return okx_payload([request.app.state.okx_store.book.balance(ccy or "")])

    @app.get(_POSITIONS_PATH)
    def read_positions(request: Request, instType: str | None = None) -> Any:
        denied = _denied(request)
        if denied is not None:
            return denied
        try:
            rows = request.app.state.okx_store.book.positions(instType or "")
        except OkxOrderError as exc:
            return okx_payload([], code=exc.s_code, msg=exc.message)
        return okx_payload(rows)

    @app.post(_ORDER_PATH)
    async def place_order_endpoint(request: Request) -> Any:
        body = (await request.body()).decode()
        denied = _denied(request, body)
        if denied is not None:
            return denied
        try:
            payload = json.loads(body)
        except ValueError:
            return okx_payload([], code=INVALID_PARAMETER_CODE, msg="Request body is not JSON")
        book = request.app.state.okx_store.book
        inst_id = str(payload.get("instId") or "")
        inst_type = request.app.state.okx_store.inst_type(inst_id)
        if inst_type is None:
            return okx_payload(
                [], code=UNKNOWN_INST_ID_CODE, msg=f"Instrument ID does not exist: {inst_id}"
            )
        try:
            order = book.place(payload, inst_type=inst_type)
        except OkxOrderError as exc:
            return JSONResponse(
                status_code=200,
                content=okx_payload(
                    [
                        {
                            "ordId": "",
                            "clOrdId": str(payload.get("clOrdId") or ""),
                            "sCode": exc.s_code,
                            "sMsg": exc.message,
                        }
                    ],
                    code=ORDER_FAILED_CODE,
                    msg="Operation failed.",
                ),
            )
        return okx_payload(
            [
                {
                    "ordId": order["ordId"],
                    "clOrdId": order["clOrdId"],
                    "sCode": "0",
                    "sMsg": "",
                }
            ]
        )

    @app.post(_CANCEL_ORDER_PATH)
    async def cancel_order_endpoint(request: Request) -> Any:
        body = (await request.body()).decode()
        denied = _denied(request, body)
        if denied is not None:
            return denied
        try:
            payload = json.loads(body)
        except ValueError:
            return okx_payload([], code=INVALID_PARAMETER_CODE, msg="Request body is not JSON")
        try:
            row = request.app.state.okx_store.book.cancel(payload)
        except OkxOrderError as exc:
            return JSONResponse(
                status_code=200,
                content=okx_payload(
                    [{"sCode": exc.s_code, "sMsg": exc.message}],
                    code=ORDER_FAILED_CODE,
                    msg="Operation failed.",
                ),
            )
        return okx_payload([{**row, "sCode": "0", "sMsg": ""}])

    @app.get(_ORDER_PATH)
    def read_order(
        request: Request,
        instId: str | None = None,
        ordId: str | None = None,
        clOrdId: str | None = None,
    ) -> Any:
        denied = _denied(request)
        if denied is not None:
            return denied
        try:
            row = request.app.state.okx_store.book.order(
                inst_id=instId or "",
                ord_id=ordId or "",
                client_order_id=clOrdId or "",
            )
        except OkxOrderError as exc:
            return okx_payload([], code=exc.s_code, msg=exc.message)
        return okx_payload([row])

    @app.get(_FILLS_PATH)
    def read_fills(
        request: Request,
        instId: str | None = None,
        ordId: str | None = None,
    ) -> Any:
        denied = _denied(request)
        if denied is not None:
            return denied
        return okx_payload(
            request.app.state.okx_store.book.fills(inst_id=instId or "", ord_id=ordId or "")
        )

    return app


def _denied(request: Request, body: str = "") -> Response | None:
    """私有端点统一验签；不通过就返回上游同款的 401 封包。

    每次调用（无论鉴权是否通过）都记进 `book.requests`：用例据此断言「发了什么」与
    「有没有发多余的请求」。
    """

    request.app.state.okx_store.book.requests.append(
        (request.method, request.url.path, request.url.query, body)
    )
    try:
        verify_request(
            headers=dict(request.headers),
            method=request.method,
            path=request.url.path,
            query=request.url.query,
            body=body,
            credentials=request.app.state.okx_store.book.credentials,
        )
    except OkxAuthError as exc:
        return JSONResponse(
            status_code=INVALID_SIGN_STATUS,
            content=okx_payload([], code=exc.code, msg=exc.message),
        )
    return None


def _parse_limit(raw: str | None, *, default: int) -> int:
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise OkxApiError(INVALID_PARAMETER_CODE, f"Parameter limit error:{raw!r}") from None


def _parse_after(raw: str | None) -> int | None:
    """`after` 按上游约定是毫秒字符串；数据源内部用秒。"""

    if raw is None:
        return None
    try:
        return int(raw) // 1000
    except ValueError:
        raise OkxApiError(INVALID_PARAMETER_CODE, f"Parameter after error:{raw!r}") from None

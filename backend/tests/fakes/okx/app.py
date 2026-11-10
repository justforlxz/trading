"""假 OKX 的 ASGI 应用。

只覆盖 T1.2 需要的 4 个公共行情端点；私有交易接口在后续节点扩展。
应答封包、业务错误码与故障注入都按真实上游行为实现，让适配器能在
不改代码的前提下直接指过来。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from tests.fakes.okx.scenarios import Scenarios
from tests.fakes.okx.store import INVALID_PARAMETER_CODE, MAX_CANDLE_LIMIT, OkxApiError, OkxStore

_INSTRUMENTS_PATH = "/api/v5/public/instruments"
_CANDLES_PATH = "/api/v5/market/candles"
_HISTORY_CANDLES_PATH = "/api/v5/market/history-candles"
_TICKER_PATH = "/api/v5/market/ticker"


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

    return app


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

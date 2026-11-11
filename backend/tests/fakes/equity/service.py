"""把假美股行情装配成 `httpx.MockTransport` 的处理函数：零网络、零端口。

处理函数按真实上游的行为校验路径与查询参数（`interval`、`period1`/`period2`、
`events`、`includeAdjustedClose`），因此测试断言请求形状时不需要另开一层桩；
`requests` 记录下来，供「拒绝时没有发出请求」这类断言使用。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from tests.fakes.equity.store import FakeEquity

__all__ = ["CHART_PREFIX", "EquityScenario", "chart_handler"]

# 上游的走势接口前缀；代码拼在后面。
CHART_PREFIX = "/v8/finance/chart/"

# 日线是唯一允许的周期；其余周期上游本身能提供，但本系统只声明日线，
# 处理函数照上游的 422 应答形状回应，用于「拒绝路径」的用例。
_SUPPORTED_INTERVAL = "1d"


@dataclass(frozen=True, slots=True)
class EquityScenario:
    """故障注入：固定状态码与应答体，用于映射上游错误。"""

    status_code: int
    body: dict[str, object] = field(default_factory=dict)


def chart_handler(
    equity: FakeEquity,
    *,
    requests: list[httpx.Request] | None = None,
    scenario: EquityScenario | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """返回一个可交给 `httpx.MockTransport` 的处理函数。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        if scenario is not None:
            return httpx.Response(scenario.status_code, json=scenario.body)

        ticker = request.url.path.removeprefix(CHART_PREFIX)
        if not request.url.path.startswith(CHART_PREFIX) or not ticker:
            return httpx.Response(404, json={"error": {"code": "Not Found"}})
        if ticker != equity.ticker:
            return httpx.Response(
                200,
                json=equity.error(
                    code="Not Found",
                    description=f"No data found, symbol may be delisted: {ticker}",
                ),
            )

        interval = request.url.params.get("interval", _SUPPORTED_INTERVAL)
        if interval != _SUPPORTED_INTERVAL:
            return httpx.Response(
                422,
                json={
                    "chart": {
                        "result": None,
                        "error": {
                            "code": "Unprocessable Entity",
                            "description": f"{interval} data not available",
                        },
                    }
                },
            )

        period1 = int(request.url.params["period1"])
        period2 = int(request.url.params["period2"])
        return httpx.Response(200, json=equity.chart(period1=period1, period2=period2))

    return handler

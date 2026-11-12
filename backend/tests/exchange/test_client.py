"""OkxClient：请求、限流重试与错误收敛（零网络，传输层注入）。"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.config import Settings
from app.exchange import ExchangeError, OkxClient, RateLimitedError


def _settings(max_retries: int = 2) -> Settings:
    return Settings(okx_rest_base_url="https://okx.test", okx_http_max_retries=max_retries)


def _client(
    handler: Any, *, max_retries: int = 2
) -> tuple[OkxClient, list[httpx.Request], list[float]]:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = OkxClient(
        settings=_settings(max_retries),
        transport=httpx.MockTransport(record),
        sleep=sleeps.append,
    )
    return client, requests, sleeps


def _ok(data: list[Any]) -> httpx.Response:
    return httpx.Response(200, json={"code": "0", "msg": "", "data": data})


def test_successful_request_returns_data() -> None:
    client, requests, _ = _client(lambda request: _ok([{"instId": "XAAPL-USDT"}]))

    with client:
        result = client.get("/api/v5/public/instruments", {"instType": "SPOT"})

    assert result == [{"instId": "XAAPL-USDT"}]
    assert len(requests) == 1
    assert requests[0].url.path == "/api/v5/public/instruments"
    assert requests[0].url.params["instType"] == "SPOT"
    assert client._client.is_closed is True


def test_successful_request_without_params_works() -> None:
    client, requests, _ = _client(lambda request: _ok([]))

    assert client.get("/api/v5/market/ticker") == []
    assert requests[0].url.params == httpx.QueryParams()
    client.close()


def test_success_payload_without_data_returns_empty_list() -> None:
    client, _, _ = _client(lambda request: httpx.Response(200, json={"code": "0"}))
    assert client.get("/api/v5/market/ticker") == []


def test_http_429_is_retried_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, text="Too Many Requests")
        return _ok([{"ok": True}])

    client, requests, sleeps = _client(handler)

    assert client.get("/api/v5/market/candles") == [{"ok": True}]
    assert len(requests) == 2
    assert sleeps == [0.25]
    client.close()


def test_http_429_exhausts_retries_into_rate_limited_error() -> None:
    client, requests, sleeps = _client(
        lambda request: httpx.Response(429, text="Too Many Requests"), max_retries=2
    )

    with pytest.raises(RateLimitedError) as excinfo:
        client.get("/api/v5/market/candles")

    assert isinstance(excinfo.value, ExchangeError)
    assert len(requests) == 3  # 首次 + 2 次重试
    assert sleeps == [0.25, 0.5]
    client.close()


def test_upstream_rate_limit_code_is_retried_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                200, json={"code": "50011", "msg": "Rate limit reached", "data": []}
            )
        return _ok([])

    client, requests, sleeps = _client(handler)

    assert client.get("/api/v5/market/ticker") == []
    assert len(requests) == 2
    assert sleeps == [0.25]
    client.close()


def test_upstream_rate_limit_code_exhausts_retries_into_rate_limited_error() -> None:
    payload = httpx.Response(200, json={"code": "50011", "msg": "Rate limit reached"})
    client, requests, _ = _client(lambda request: payload, max_retries=2)

    with pytest.raises(RateLimitedError) as excinfo:
        client.get("/api/v5/market/ticker")

    assert excinfo.value.code == "50011"
    assert len(requests) == 3
    client.close()


def test_http_400_with_a_rate_limit_code_is_treated_as_rate_limited() -> None:
    """限流判定只看返回码：HTTP 4xx 里带 50011 与 HTTP 429 是同一件事，都要重试。"""

    payload = httpx.Response(400, json={"code": "50011", "msg": "Too Many Requests"})
    client, requests, sleeps = _client(lambda request: payload, max_retries=1)

    with pytest.raises(RateLimitedError) as excinfo:
        client.get("/api/v5/market/ticker")

    assert excinfo.value.code == "50011"
    assert len(requests) == 2
    assert sleeps == [0.25]
    client.close()


def test_other_upstream_code_maps_to_exchange_error_without_retry() -> None:
    payload = httpx.Response(
        200, json={"code": "51001", "msg": "Instrument ID does not exist", "data": []}
    )
    client, requests, sleeps = _client(lambda request: payload)

    with pytest.raises(ExchangeError) as excinfo:
        client.get("/api/v5/market/ticker", {"instId": "AAPL-USDT"})

    assert not isinstance(excinfo.value, RateLimitedError)
    assert excinfo.value.code == "51001"
    assert "Instrument ID does not exist" in str(excinfo.value)
    assert len(requests) == 1
    assert sleeps == []
    client.close()


@pytest.mark.parametrize("status", [400, 404, 500, 503])
def test_http_error_status_maps_to_exchange_error(status: int) -> None:
    client, requests, sleeps = _client(lambda request: httpx.Response(status, text="boom"))

    with pytest.raises(ExchangeError) as excinfo:
        client.get("/api/v5/market/ticker")

    assert str(status) in str(excinfo.value)
    assert len(requests) == 1
    assert sleeps == []
    client.close()


def test_non_json_body_maps_to_exchange_error() -> None:
    client, _, _ = _client(lambda request: httpx.Response(200, text="<html>nope</html>"))

    with pytest.raises(ExchangeError, match="非 JSON"):
        client.get("/api/v5/market/ticker")

    client.close()


def test_non_object_json_body_maps_to_exchange_error() -> None:
    client, _, _ = _client(lambda request: httpx.Response(200, json=[1, 2, 3]))

    with pytest.raises(ExchangeError, match="结构异常"):
        client.get("/api/v5/market/ticker")

    client.close()


def test_transport_error_maps_to_exchange_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client, _, _ = _client(handler)

    with pytest.raises(ExchangeError, match=r"请求 .* 失败"):
        client.get("/api/v5/market/ticker")

    client.close()


def test_timeout_maps_to_exchange_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client, _, _ = _client(handler)

    with pytest.raises(ExchangeError, match=r"请求 .* 失败"):
        client.get("/api/v5/market/ticker")

    client.close()

"""假 OKX 的 HTTP 契约：封包、分页、参数校验与故障注入。"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.fakes.okx.scenarios import Scenarios

_INSTRUMENTS = "/api/v5/public/instruments"
_CANDLES = "/api/v5/market/candles"
_HISTORY = "/api/v5/market/history-candles"
_TICKER = "/api/v5/market/ticker"


@pytest.fixture()
def okx_api(fake_okx_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(fake_okx_app) as test_client:
        yield test_client


@pytest.fixture()
def scenarios(fake_okx_app: FastAPI) -> Scenarios:
    active: Scenarios = fake_okx_app.state.okx_scenarios
    return active


def test_instruments_endpoint_returns_the_spot_universe(okx_api: TestClient) -> None:
    response = okx_api.get(_INSTRUMENTS, params={"instType": "SPOT"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == "0"
    assert payload["msg"] == ""
    assert len(payload["data"]) == 199


def test_missing_inst_type_is_a_business_error_not_a_422(okx_api: TestClient) -> None:
    response = okx_api.get(_INSTRUMENTS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == "51000"
    assert payload["data"] == []


def test_candles_endpoint_defaults_to_a_full_page(okx_api: TestClient) -> None:
    payload = okx_api.get(_CANDLES, params={"instId": "XAAPL-USDT", "bar": "1D"}).json()

    assert payload["code"] == "0"
    rows = payload["data"]
    assert len(rows) == 100
    assert all(len(row) == 9 for row in rows)
    assert rows[0][8] == "0"
    timestamps = [int(row[0]) for row in rows]
    assert timestamps == sorted(timestamps, reverse=True)


def test_candles_endpoint_honours_limit(okx_api: TestClient) -> None:
    payload = okx_api.get(
        _CANDLES, params={"instId": "XAAPL-USDT", "bar": "1H", "limit": "3"}
    ).json()

    assert len(payload["data"]) == 3


def test_candles_endpoint_rejects_out_of_range_limit(okx_api: TestClient) -> None:
    payload = okx_api.get(
        _CANDLES, params={"instId": "XAAPL-USDT", "bar": "1H", "limit": "101"}
    ).json()

    assert payload["code"] == "51000"


def test_candles_endpoint_rejects_unknown_instrument(okx_api: TestClient) -> None:
    payload = okx_api.get(_CANDLES, params={"instId": "XNOTREAL-USDT", "bar": "1H"}).json()

    assert payload["code"] == "51001"


def test_history_candles_honours_the_millisecond_cursor(okx_api: TestClient) -> None:
    recent = okx_api.get(
        _CANDLES, params={"instId": "XAAPL-USDT", "bar": "1H", "limit": "5"}
    ).json()["data"]
    cursor = recent[-1][0]

    older = okx_api.get(
        _HISTORY,
        params={"instId": "XAAPL-USDT", "bar": "1H", "after": cursor, "limit": "5"},
    ).json()["data"]

    assert older
    assert all(int(row[0]) < int(cursor) for row in older)
    assert {row[8] for row in older} == {"1"}


def test_ticker_endpoint_returns_a_single_row(okx_api: TestClient) -> None:
    payload = okx_api.get(_TICKER, params={"instId": "XAAPL-USDT"}).json()

    assert payload["code"] == "0"
    assert len(payload["data"]) == 1
    assert payload["data"][0]["instId"] == "XAAPL-USDT"


def test_ticker_endpoint_rejects_unknown_instrument(okx_api: TestClient) -> None:
    payload = okx_api.get(_TICKER, params={"instId": "XNOTREAL-USDT"}).json()

    assert payload["code"] == "51001"


def test_rate_limited_scenario_returns_http_429(okx_api: TestClient, scenarios: Scenarios) -> None:
    scenarios.activate("rate_limited")

    response = okx_api.get(_INSTRUMENTS, params={"instType": "SPOT"})

    assert response.status_code == 429
    assert response.json()["code"] == "50011"

    scenarios.reset()
    assert okx_api.get(_INSTRUMENTS, params={"instType": "SPOT"}).status_code == 200


def test_upstream_error_scenario_returns_http_500(
    okx_api: TestClient, scenarios: Scenarios
) -> None:
    scenarios.activate("upstream_error")

    response = okx_api.get(_INSTRUMENTS, params={"instType": "SPOT"})

    assert response.status_code == 500
    assert response.json()["code"] == "50001"


def test_slow_scenario_delays_the_response(okx_api: TestClient, scenarios: Scenarios) -> None:
    scenarios.slow(0.05)

    started = time.monotonic()
    response = okx_api.get(_INSTRUMENTS, params={"instType": "SPOT"})
    elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert elapsed >= 0.05


def test_unknown_scenario_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="未知场景"):
        Scenarios().activate("not_a_scenario")

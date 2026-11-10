"""假 OKX 的独立进程形态：真实端口可达，故障开关可运行期切换。"""

from __future__ import annotations

import httpx

from tests.fakes.okx.server import FakeOkxServer, start_server

_INSTRUMENTS = "/api/v5/public/instruments"


def test_server_listens_on_a_real_port(fake_okx_server: FakeOkxServer) -> None:
    assert fake_okx_server.port > 0
    assert fake_okx_server.base_url.startswith("http://127.0.0.1:")

    response = httpx.get(f"{fake_okx_server.base_url}{_INSTRUMENTS}", params={"instType": "SPOT"})

    assert response.status_code == 200
    assert len(response.json()["data"]) == 199


def test_scenarios_can_be_switched_on_a_running_server(fake_okx_server: FakeOkxServer) -> None:
    url = f"{fake_okx_server.base_url}{_INSTRUMENTS}"

    fake_okx_server.scenarios.activate("rate_limited")
    limited = httpx.get(url, params={"instType": "SPOT"})

    assert limited.status_code == 429
    assert limited.json()["code"] == "50011"

    fake_okx_server.scenarios.reset()
    assert httpx.get(url, params={"instType": "SPOT"}).status_code == 200


def test_start_server_allocates_a_free_port_when_asked() -> None:
    with start_server(port=0) as server:
        assert server.port > 0
        response = httpx.get(
            f"{server.base_url}/api/v5/market/ticker", params={"instId": "XAAPL-USDT"}
        )

    assert response.json()["code"] == "0"
